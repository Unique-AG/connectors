import assert from 'node:assert';
import { AesGcmEncryptionService } from '@unique-ag/aes-gcm-encryption';
import {
  AuthenticationProvider,
  AuthenticationProviderOptions,
} from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { DrizzleDatabase } from '../db/drizzle.module';
import { userProfiles } from '../db/schema';

export class TokenProvider implements AuthenticationProvider {
  private readonly logger = new Logger(TokenProvider.name);
  private readonly userProfileId: string;
  private readonly clientId: string;
  private readonly clientSecret: string;
  private readonly scopes: string[];
  private readonly drizzle: DrizzleDatabase;
  private readonly encryptionService: AesGcmEncryptionService;

  public constructor(
    {
      userProfileId,
      clientId,
      clientSecret,
      scopes,
    }: {
      userProfileId: string;
      clientId: string;
      clientSecret: string;
      scopes: string[];
    },
    {
      drizzle,
      encryptionService,
    }: {
      drizzle: DrizzleDatabase;
      encryptionService: AesGcmEncryptionService;
    },
  ) {
    this.userProfileId = userProfileId;
    this.clientId = clientId;
    this.clientSecret = clientSecret;
    this.scopes = scopes;
    this.drizzle = drizzle;
    this.encryptionService = encryptionService;
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
      const response = await fetch('https://login.microsoftonline.com/common/oauth2/v2.0/token', {
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
        this.logger.error(
          {
            status: response.status,
            errorText,
            userProfileId: this.userProfileId,
            tokenRefreshFailed: true,
            errorSource: 'microsoft_graph_api',
          },
          'Microsoft Graph API rejected token refresh request',
        );
        assert.fail(`Token refresh failed: ${response.statusText}`);
      }

      const tokenData = await response.json();

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
          userProfileId: this.userProfileId,
          tokenRefreshSuccess: true,
          action: 'token_refresh_completed',
        },
        'Successfully refreshed Microsoft Graph API access token',
      );
      return tokenData.access_token;
    } catch (error) {
      this.logger.error(
        'Failed to refresh Microsoft Graph API access token for user',
        {
          userProfileId: this.userProfileId,
          tokenRefreshFailed: true,
          errorSource: 'microsoft_graph_api',
        },
        error,
      );
      throw new Error(
        `Token refresh failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
      );
    }
  }
}
