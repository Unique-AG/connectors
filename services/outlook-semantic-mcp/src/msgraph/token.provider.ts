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
import { eq } from 'drizzle-orm';
import { isObjectType } from 'remeda';
import { type Dispatcher, fetch, type Response } from 'undici';
import { z } from 'zod';
import { authorizeTenant, microsoftOAuthTokenUrl } from '../auth/microsoft.provider';
import { DrizzleDatabase } from '../db/drizzle.module';
import { CLEARED_TOKEN_REFRESH_BACKOFF, userProfiles } from '../db/schema';
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
   * Every TokenProvider in the process shares one refresh per user, so a burst of 401s for the
   * same user calls Microsoft once. Pass the access token Graph rejected so a request that lost the
   * race reuses the token another request already stored instead of refreshing again.
   */
  public refreshAccessToken(userProfileId: string, rejectedAccessToken?: string): Promise<string> {
    const inFlight = inFlightRefreshes.get(userProfileId);
    if (inFlight) {
      return inFlight;
    }
    const refresh = this.refreshOnce(userProfileId, rejectedAccessToken).finally(() =>
      inFlightRefreshes.delete(userProfileId),
    );
    inFlightRefreshes.set(userProfileId, refresh);
    return refresh;
  }

  private async refreshOnce(userProfileId: string, rejectedAccessToken?: string): Promise<string> {
    const userProfile = await this.drizzle.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });

    assert.ok(userProfile?.refreshToken, `No refresh token available for user: ${userProfileId}`);

    if (rejectedAccessToken && userProfile.accessToken) {
      const storedAccessToken = this.encryptionService
        .decryptFromString(userProfile.accessToken)
        .toString('utf-8');
      addLogSecrets([storedAccessToken]);
      if (storedAccessToken !== rejectedAccessToken) {
        this.logger.debug({
          msg: 'Microsoft Graph access token was already refreshed, reusing the stored one',
          userProfileId,
        });
        return storedAccessToken;
      }
    }

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

    if (!response.ok) {
      const oauthError = parseOAuthError(await response.text());

      // Errors handled:
      // - isPermanentUpstreamOAuthError: invalid_grant, interaction_required, consent_required
      //   (user revoked consent or the refresh grant expired)
      // - isAppLevelOAuthError: invalid_client, unauthorized_client
      //   Error triggered by: Entra app registration change — e.g. the client secret was
      //   rotated, or the secret ID was configured instead of the secret value
      //   (AADSTS7000215). Clear stored tokens so we do not retry the same refresh forever.
      if (
        isPermanentUpstreamOAuthError(oauthError.error) ||
        isAppLevelOAuthError(oauthError.error)
      ) {
        return await this.revokeUpstreamCredential(userProfileId, {
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
        retryAfterMs: parseRetryAfterMs(response.headers.get('retry-after')),
        message: `Token refresh failed: ${response.statusText}`,
      });
    }

    const tokenData = TokenRefreshResponseSchema.parse(await response.json());
    addLogSecrets([
      tokenData.access_token,
      ...(tokenData.refresh_token ? [tokenData.refresh_token] : []),
    ]);

    const tenant = authorizeTenant(tokenData.access_token, this.allowedTenantIds);
    if (!tenant.allowed) {
      return await this.revokeUpstreamCredential(userProfileId, {
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
      .where(eq(userProfiles.id, userProfileId));

    this.logger.debug({
      msg: 'Successfully refreshed Microsoft Graph API access token',
      userProfileId,
      tokenRefreshSuccess: true,
      action: 'token_refresh_completed',
    });
    return tokenData.access_token;
  }

  /**
   * Backs off before the next refresh attempt: Microsoft's Retry-After when it sends one,
   * otherwise 1, 2, 4… minutes per consecutive failure, capped at 30 minutes.
   */
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
    const backoffMs = Math.min(
      retryAfterMs ?? MIN_REFRESH_BACKOFF_MS * 2 ** (failureCount - 1),
      MAX_REFRESH_BACKOFF_MS,
    );
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
      .where(eq(userProfiles.id, userProfile.id));

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
    userProfileId: string,
    {
      reason,
      failureCode,
      aadstsCodes,
    }: { reason?: string; failureCode: string; aadstsCodes?: number[] },
  ): Promise<never> {
    await this.drizzle
      .update(userProfiles)
      .set({ accessToken: null, refreshToken: null })
      .where(eq(userProfiles.id, userProfileId));

    await this.onPermanentAuthFailure?.(userProfileId);
    this.logger.warn({
      msg: 'Microsoft grant is permanently invalid; cleared the Graph tokens and revoked the MCP session',
      userProfileId,
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

const parseRetryAfterMs = (retryAfter: string | null): number | null => {
  const seconds = Number.parseInt(retryAfter ?? '', 10);
  return Number.isNaN(seconds) ? null : seconds * 1000;
};

const networkFailureCode = (error: unknown): string => {
  const cause = isObjectType(error) && 'cause' in error ? error.cause : undefined;
  const code = isObjectType(cause) && 'code' in cause ? cause.code : undefined;
  return `network_${typeof code === 'string' ? code : 'unknown'}`;
};
