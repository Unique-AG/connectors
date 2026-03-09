import assert from 'node:assert';
import { AesGcmEncryptionService } from '@unique-ag/aes-gcm-encryption';
import {
  AuthenticationProvider,
  AuthenticationProviderOptions,
} from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { serializeError } from 'serialize-error-cjs';
import { DrizzleDatabase } from '../drizzle/drizzle.module';
import { userProfiles } from '../drizzle/schema';
import { normalizeError } from '../utils/normalize-error';

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
    return decrypedAccessToken.toString('utf-8');
  }

  public async refreshAccessToken(userProfileId: string): Promise<string> {
    const userProfile = await this.drizzle.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });

    assert.ok(userProfile?.refreshToken, `No refresh token available for user: ${userProfileId}`);

    const decrypedRefreshToken = this.encryptionService.decryptFromString(userProfile.refreshToken);

    try {
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
          },
          'Microsoft Graph API rejected token refresh request',
        );
        assert.fail(`Token refresh failed: ${response.statusText}`);
      }

      const tokenData = await response.json();

      const encryptedAccessToken = this.encryptionService.encryptToString(tokenData.access_token);
      const encryptedRefreshToken = tokenData.refresh_token
        ? this.encryptionService.encryptToString(tokenData.refresh_token)
        : userProfile.refreshToken;

      await this.drizzle
        .update(userProfiles)
        .set({
          accessToken: encryptedAccessToken,
          refreshToken: encryptedRefreshToken,
        })
        .where(eq(userProfiles.id, userProfileId));

      return tokenData.access_token;
    } catch (error) {
      this.logger.error(
        {
          userProfileId: this.userProfileId,
          error: serializeError(normalizeError(error)),
          tokenRefreshFailed: true,
        },
        'Failed to refresh Microsoft Graph API access token',
      );
      throw new Error(
        `Token refresh failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
      );
    }
  }
}
