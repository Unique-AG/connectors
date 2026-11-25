import assert from 'node:assert';
import { AesGcmEncryptionService } from '@unique-ag/aes-gcm-encryption';
import { addLogSecrets } from '@unique-ag/logger';
import {
  isPermanentUpstreamOAuthError,
  UpstreamCredentialRevokedError,
} from '@unique-ag/mcp-oauth';
import {
  AuthenticationProvider,
  AuthenticationProviderOptions,
} from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { isObjectType } from 'remeda';
import { type Dispatcher, fetch, type Response } from 'undici';
import { z } from 'zod';
import { authorizeTenant, microsoftOAuthTokenUrl } from '../auth/microsoft.provider';
import { DrizzleDatabase } from '../db/drizzle.module';
import { CLEARED_TOKEN_REFRESH_BACKOFF, userProfiles } from '../db/schema';
import { parseRetryAfterMs } from '../utils/parse-retry-after-ms';
import { isAppLevelOAuthError } from './is-app-level-oauth-error';

const TokenRefreshResponseSchema = z.object({
  access_token: z.string().min(1),
  refresh_token: z.string().min(1).optional(),
});

export class TokenProvider implements AuthenticationProvider {
  private readonly logger = new Logger(TokenProvider.name);
  private readonly userProfileId: string;
  private readonly clientId: string;
  private readonly clientSecret: string;
  private readonly signInTenantId: string;
  private readonly allowedTenantIds: string[];
  private readonly scopes: string[];
  private readonly drizzle: DrizzleDatabase;
  private readonly encryptionService: AesGcmEncryptionService;
  private readonly dispatcher: Dispatcher;
  private readonly onPermanentAuthFailure?: (userProfileId: string) => Promise<void>;

  public constructor(
    {
      userProfileId,
      clientId,
      clientSecret,
      signInTenantId,
      allowedTenantIds,
      scopes,
    }: {
      userProfileId: string;
      clientId: string;
      clientSecret: string;
      signInTenantId: string;
      allowedTenantIds: string[];
      scopes: string[];
    },
    {
      drizzle,
      encryptionService,
      dispatcher,
      onPermanentAuthFailure,
    }: {
      drizzle: DrizzleDatabase;
      encryptionService: AesGcmEncryptionService;
      dispatcher: Dispatcher;
      onPermanentAuthFailure?: (userProfileId: string) => Promise<void>;
    },
  ) {
    this.userProfileId = userProfileId;
    this.clientId = clientId;
    this.clientSecret = clientSecret;
    this.signInTenantId = signInTenantId;
    this.allowedTenantIds = allowedTenantIds;
    this.scopes = scopes;
    this.drizzle = drizzle;
    this.encryptionService = encryptionService;
    this.dispatcher = dispatcher;
    this.onPermanentAuthFailure = onPermanentAuthFailure;
  }

  public async getAccessToken(
    _authenticationProviderOptions?: AuthenticationProviderOptions,
  ): Promise<string> {
    const userProfile = await this.drizzle.query.userProfiles.findFirst({
      where: eq(userProfiles.id, this.userProfileId),
    });

    assert.ok(userProfile, `User profile not found: ${this.userProfileId}`);
    assert.ok(userProfile.accessToken, `Access token not found for user: ${this.userProfileId}`);

    const accessToken = this.encryptionService
      .decryptFromString(userProfile.accessToken)
      .toString('utf-8');
    addLogSecrets([accessToken]);

    // Return the access token directly
    // If the token is expired, the Microsoft Graph SDK will handle the error
    // when making actual API calls, and you can implement retry logic there
    return accessToken;
  }

  /**
   * One refresh per user across the process. A request whose rejected token was already replaced
   * reuses the stored one.
   */
  public async refreshAccessToken(
    userProfileId: string,
    rejectedAccessToken?: string,
  ): Promise<string> {
    const inFlight = inFlightRefreshes.get(userProfileId);
    if (inFlight) {
      return inFlight;
    }
    if (rejectedAccessToken) {
      const storedAccessToken = await this.readStoredAccessToken(userProfileId);
      if (storedAccessToken && storedAccessToken !== rejectedAccessToken) {
        this.logger.debug({
          msg: 'Microsoft Graph access token was already refreshed, reusing the stored one',
          userProfileId,
        });
        return storedAccessToken;
      }
    }
    // Another request may have started the refresh while the stored token was read.
    const startedMeanwhile = inFlightRefreshes.get(userProfileId);
    if (startedMeanwhile) {
      return startedMeanwhile;
    }
    const refresh = this.refreshOnce(userProfileId).finally(() =>
      inFlightRefreshes.delete(userProfileId),
    );
    inFlightRefreshes.set(userProfileId, refresh);
    return refresh;
  }

  private async readStoredAccessToken(userProfileId: string): Promise<string | undefined> {
    const userProfile = await this.drizzle.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    if (!userProfile?.accessToken) {
      return undefined;
    }
    const accessToken = this.encryptionService
      .decryptFromString(userProfile.accessToken)
      .toString('utf-8');
    addLogSecrets([accessToken]);
    return accessToken;
  }

  private async refreshOnce(userProfileId: string): Promise<string> {
    const userProfile = await this.drizzle.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });

    assert.ok(userProfile?.refreshToken, `No refresh token available for user: ${userProfileId}`);

    if (userProfile.tokenRefreshRetryAt && userProfile.tokenRefreshRetryAt > new Date()) {
      throw new TokenRefreshCoolingDownError(userProfile.tokenRefreshRetryAt);
    }

    const refreshToken = this.encryptionService
      .decryptFromString(userProfile.refreshToken)
      .toString('utf-8');
    addLogSecrets([refreshToken]);

    let response: Response;
    try {
      response = await fetch(microsoftOAuthTokenUrl(this.signInTenantId), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams({
          grant_type: 'refresh_token',
          refresh_token: refreshToken,
          client_id: this.clientId,
          client_secret: this.clientSecret,
          scope: this.scopes.join(' '),
        }),
        dispatcher: this.dispatcher,
      });
    } catch (err) {
      return await this.recordTransientFailure(userProfile, {
        failureCode: networkFailureCode(err),
        retryAfterMs: null,
        message: `Token refresh failed: ${err instanceof Error ? err.message : 'Unknown error'}`,
        cause: err,
      });
    }

    // The connection can drop after the status and headers arrived, so a body that cannot be read
    // backs off like any other transient failure, keeping the status and Retry-After.
    const retryAfterMs = () => parseRetryAfterMs(response.headers.get('retry-after'));
    const unreadableBody = (cause: unknown) =>
      this.recordTransientFailure(userProfile, {
        failureCode: `http_${response.status}_unreadable_body`,
        retryAfterMs: retryAfterMs(),
        message: `Token refresh failed: ${response.statusText}`,
        cause,
      });

    if (!response.ok) {
      let body: string;
      try {
        body = await response.text();
      } catch (err) {
        return await unreadableBody(err);
      }
      const oauthError = parseOAuthError(body);

      // Neither a dead grant nor a broken app registration succeeds on retry, so the tokens go.
      if (
        isPermanentUpstreamOAuthError(oauthError.error) ||
        isAppLevelOAuthError(oauthError.error)
      ) {
        return await this.revokeUpstreamCredential(userProfile, {
          reason: oauthError.error_description,
          failureCode: `http_${response.status}_${oauthError.error}`,
          aadstsCodes: oauthError.error_codes,
        });
      }

      return await this.recordTransientFailure(userProfile, {
        failureCode: oauthError.error
          ? `http_${response.status}_${oauthError.error}`
          : `http_${response.status}`,
        aadstsCodes: oauthError.error_codes,
        retryAfterMs: retryAfterMs(),
        message: `Token refresh failed: ${response.statusText}`,
      });
    }

    let tokenData: z.infer<typeof TokenRefreshResponseSchema>;
    try {
      tokenData = TokenRefreshResponseSchema.parse(await response.json());
    } catch (err) {
      return await unreadableBody(err);
    }
    addLogSecrets([
      tokenData.access_token,
      ...(tokenData.refresh_token ? [tokenData.refresh_token] : []),
    ]);

    const tenant = authorizeTenant(tokenData.access_token, this.allowedTenantIds);
    if (!tenant.allowed) {
      return await this.revokeUpstreamCredential(userProfile, {
        reason: tenant.reason,
        failureCode: 'tenant_not_allowed',
      });
    }

    const encryptedAccessToken = this.encryptionService.encryptToString(tokenData.access_token);
    // Keep old refresh token if new one not provided
    const encryptedRefreshToken = tokenData.refresh_token
      ? this.encryptionService.encryptToString(tokenData.refresh_token)
      : userProfile.refreshToken;

    await this.drizzle
      .update(userProfiles)
      .set({
        accessToken: encryptedAccessToken,
        refreshToken: encryptedRefreshToken,
        ...CLEARED_TOKEN_REFRESH_BACKOFF,
      })
      // A sign-in that stored a new grant meanwhile keeps it; the token refreshed here still works.
      .where(isSameGrant(userProfile));

    this.logger.debug({
      msg: 'Successfully refreshed Microsoft Graph API access token',
      userProfileId,
      tokenRefreshSuccess: true,
      action: 'token_refresh_completed',
    });
    return tokenData.access_token;
  }

  /** Backs off by Retry-After, else 1, 2, 4… minutes capped at 30, on the grant it tried only. */
  private async recordTransientFailure(
    userProfile: UserProfile,
    {
      failureCode,
      aadstsCodes,
      retryAfterMs,
      message,
      cause,
    }: {
      failureCode: string;
      aadstsCodes?: number[];
      retryAfterMs: number | null;
      message: string;
      cause?: unknown;
    },
  ): Promise<never> {
    const failureCount = userProfile.tokenRefreshFailureCount + 1;
    const backoffMs =
      retryAfterMs ??
      Math.min(MIN_REFRESH_BACKOFF_MS * 2 ** (failureCount - 1), MAX_REFRESH_BACKOFF_MS);
    const failedAt = new Date();
    const retryAt = new Date(failedAt.getTime() + backoffMs);

    await this.drizzle
      .update(userProfiles)
      .set({
        tokenRefreshFailedAt: failedAt,
        tokenRefreshFailureCount: failureCount,
        tokenRefreshFailureCode: failureCode,
        tokenRefreshRetryAt: retryAt,
      })
      .where(isSameGrant(userProfile));

    this.logger.error({
      msg: 'Failed to refresh Microsoft Graph API access token for user',
      userProfileId: userProfile.id,
      tokenRefreshFailed: true,
      errorSource: 'microsoft_graph_api',
      failureCode,
      aadstsCodes,
      failureCount,
      retryAt: retryAt.toISOString(),
      err: cause,
    });
    throw new Error(message, { cause });
  }

  private async revokeUpstreamCredential(
    userProfile: UserProfile,
    {
      reason,
      failureCode,
      aadstsCodes,
    }: { reason?: string; failureCode: string; aadstsCodes?: number[] },
  ): Promise<never> {
    const cleared = await this.drizzle
      .update(userProfiles)
      .set({ accessToken: null, refreshToken: null })
      .where(isSameGrant(userProfile))
      .returning({ id: userProfiles.id });

    if (!cleared.length) {
      this.logger.warn({
        msg: 'Microsoft rejected a grant that a new sign-in has since replaced; kept the new grant and the MCP session',
        userProfileId: userProfile.id,
        failureCode,
        aadstsCodes,
      });
      throw new Error('Token refresh failed: the grant was replaced by a new sign-in');
    }

    await this.onPermanentAuthFailure?.(userProfile.id);
    this.logger.warn({
      msg: 'Microsoft grant is permanently invalid; cleared the Graph tokens and revoked the MCP session',
      userProfileId: userProfile.id,
      failureCode,
      aadstsCodes,
    });
    throw new UpstreamCredentialRevokedError(reason);
  }
}

const MIN_REFRESH_BACKOFF_MS = 60_000;
const MAX_REFRESH_BACKOFF_MS = 30 * 60_000;

const inFlightRefreshes = new Map<string, Promise<string>>();

type UserProfile = typeof userProfiles.$inferSelect;

// Matches the row only while it still holds the refresh token this refresh read.
const isSameGrant = (userProfile: UserProfile) =>
  and(
    eq(userProfiles.id, userProfile.id),
    eq(userProfiles.refreshToken, userProfile.refreshToken ?? ''),
  );

export class TokenRefreshCoolingDownError extends Error {
  public constructor(public readonly retryAt: Date) {
    super(`Microsoft token refresh is backing off until ${retryAt.toISOString()}`);
    this.name = 'TokenRefreshCoolingDownError';
  }
}

// Microsoft's error body also carries trace and correlation ids, timestamps and, for
// invalid_client, the app id; only the fields below are read so none of those reach the logs.
const OAuthErrorSchema = z.object({
  error: z.string().optional().catch(undefined),
  error_description: z.string().optional().catch(undefined),
  error_codes: z.array(z.number()).optional().catch(undefined),
});

const parseOAuthError = (body: string): z.infer<typeof OAuthErrorSchema> => {
  try {
    return OAuthErrorSchema.parse(JSON.parse(body));
  } catch {
    return {};
  }
};

const networkFailureCode = (error: unknown): string => {
  const cause = isObjectType(error) && 'cause' in error ? error.cause : undefined;
  const code = isObjectType(cause) && 'code' in cause ? cause.code : undefined;
  return `network_${typeof code === 'string' ? code : 'unknown'}`;
};
