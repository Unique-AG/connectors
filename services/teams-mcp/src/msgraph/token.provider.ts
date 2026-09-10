import assert from 'node:assert';
import { AesGcmEncryptionService } from '@unique-ag/aes-gcm-encryption';
import {
  isPermanentUpstreamOAuthError,
  isUpstreamCredentialRevokedError,
  UpstreamCredentialRevokedError,
} from '@unique-ag/mcp-oauth';
import {
  AuthenticationProvider,
  AuthenticationProviderOptions,
} from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { serializeError } from 'serialize-error-cjs';
import { z } from 'zod';
import { microsoftOAuthTokenUrl } from '../auth/microsoft.provider';
import { DrizzleDatabase } from '../drizzle/drizzle.module';
import { userProfiles } from '../drizzle/schema';
import { normalizeError } from '../utils/normalize-error';

/** Microsoft OAuth2 token-refresh response — only the fields this provider consumes. */
const TokenRefreshResponse = z.object({
  access_token: z.string(),
  refresh_token: z.string().optional(),
});

export class TokenProvider implements AuthenticationProvider {
  private readonly logger = new Logger(TokenProvider.name);
  private readonly userProfileId: string;
  private readonly clientId: string;
  private readonly clientSecret: string;
  private readonly signInTenantId: string;
  private readonly scopes: string[];
  private readonly drizzle: DrizzleDatabase;
  private readonly encryptionService: AesGcmEncryptionService;
  private readonly onPermanentAuthFailure?: (userProfileId: string) => Promise<void>;

  public constructor(
    {
      userProfileId,
      clientId,
      clientSecret,
      signInTenantId,
      scopes,
    }: {
      userProfileId: string;
      clientId: string;
      clientSecret: string;
      signInTenantId: string;
      scopes: string[];
    },
    {
      drizzle,
      encryptionService,
      onPermanentAuthFailure,
    }: {
      drizzle: DrizzleDatabase;
      encryptionService: AesGcmEncryptionService;
      onPermanentAuthFailure?: (userProfileId: string) => Promise<void>;
    },
  ) {
    this.userProfileId = userProfileId;
    this.clientId = clientId;
    this.clientSecret = clientSecret;
    this.signInTenantId = signInTenantId;
    this.scopes = scopes;
    this.drizzle = drizzle;
    this.encryptionService = encryptionService;
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

    const decrypedAccessToken = this.encryptionService.decryptFromString(userProfile.accessToken);

    // Return the access token directly
    // If the token is expired, the Microsoft Graph SDK will handle the error
    // when making actual API calls, and you can implement retry logic there
    return decrypedAccessToken.toString('utf-8');
  }

  public async refreshAccessToken(userProfileId: string): Promise<string> {
    const userProfile = await this.drizzle.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });

    assert.ok(userProfile?.refreshToken, `No refresh token available for user: ${userProfileId}`);

    const decrypedRefreshToken = this.encryptionService.decryptFromString(userProfile.refreshToken);

    try {
      // Microsoft OAuth2 token refresh endpoint
      const response = await fetch(microsoftOAuthTokenUrl(this.signInTenantId), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams({
          grant_type: 'refresh_token',
          refresh_token: decrypedRefreshToken.toString('utf-8'),
          client_id: this.clientId,
          client_secret: this.clientSecret,
          scope: this.scopes.join(' '),
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        let parsedError: { error?: string; error_description?: string } = {};
        try {
          parsedError = JSON.parse(errorText);
        } catch {
          // not JSON
        }

        this.logger.error(
          {
            status: response.status,
            errorText,
            userProfileId,
            tokenRefreshFailed: true,
            errorSource: 'microsoft_graph_api',
          },
          'Microsoft Graph API rejected token refresh request',
        );

        if (isPermanentUpstreamOAuthError(parsedError.error)) {
          await this.drizzle
            .update(userProfiles)
            .set({ accessToken: null, refreshToken: null })
            .where(eq(userProfiles.id, userProfileId));

          await this.onPermanentAuthFailure?.(userProfileId);
          throw new UpstreamCredentialRevokedError(parsedError.error_description);
        }

        assert.fail(`Token refresh failed: ${response.statusText}`);
      }

      const tokenData = TokenRefreshResponse.parse(await response.json());

      const encryptedAccessToken = this.encryptionService.encryptToString(tokenData.access_token);
      // Keep old refresh token if new one not provided
      const encryptedRefreshToken = tokenData.refresh_token
        ? this.encryptionService.encryptToString(tokenData.refresh_token)
        : userProfile.refreshToken;

      // Update the stored tokens
      await this.drizzle
        .update(userProfiles)
        .set({
          accessToken: encryptedAccessToken,
          refreshToken: encryptedRefreshToken,
        })
        .where(eq(userProfiles.id, userProfileId));

      this.logger.debug(
        {
          userProfileId,
          tokenRefreshSuccess: true,
          action: 'token_refresh_completed',
        },
        'Successfully refreshed Microsoft Graph API access token',
      );
      return tokenData.access_token;
    } catch (error) {
      if (isUpstreamCredentialRevokedError(error)) {
        this.logger.warn(
          {
            userProfileId,
            error: serializeError(normalizeError(error)),
          },
          'Microsoft grant is permanently invalid; propagating after MCP token revoke',
        );
        throw error;
      }
      this.logger.error(
        {
          userProfileId,
          error: serializeError(normalizeError(error)),
          tokenRefreshFailed: true,
          errorSource: 'microsoft_graph_api',
        },
        'Failed to refresh Microsoft Graph API access token for user',
      );
      throw new Error(
        `Token refresh failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
      );
    }
  }
}
