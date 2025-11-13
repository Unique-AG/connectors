import { DefaultAzureCredential } from '@azure/identity';
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
  private readonly credential: DefaultAzureCredential;
  private readonly tenantId?: string;

  public constructor(
    {
      userProfileId,
      clientId,
      clientSecret,
      scopes,
      tenantId,
    }: {
      userProfileId: string;
      clientId: string;
      clientSecret: string;
      scopes: string[];
      tenantId?: string;
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
    this.tenantId = tenantId;
    this.drizzle = drizzle;
    this.encryptionService = encryptionService;
    this.credential = new DefaultAzureCredential({ tenantId });
  }

  public async getAccessToken(
    _authenticationProviderOptions?: AuthenticationProviderOptions,
  ): Promise<string> {
    const userProfile = await this.drizzle.query.userProfiles.findFirst({
      where: eq(userProfiles.id, this.userProfileId),
    });

    if (!userProfile) throw new Error(`User profile not found: ${this.userProfileId}`);
    if (!userProfile.accessToken)
      throw new Error(`Access token not found for user: ${this.userProfileId}`);

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

    if (!userProfile?.refreshToken)
      throw new Error(`No refresh token available for user: ${this.userProfileId}`);

    const decrypedRefreshToken = this.encryptionService.decryptFromString(userProfile.refreshToken);

    try {
      // Get client assertion token using Azure Workload Identity
      const clientAssertion = await this.credential.getToken(
        'https://login.microsoftonline.com/.default',
      );

      if (!clientAssertion?.token) {
        throw new Error('Failed to acquire client assertion token from workload identity');
      }

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
          client_assertion: clientAssertion.token,
          client_assertion_type: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
          scope: this.scopes.join(' '),
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        this.logger.error(`Token refresh failed: ${response.status} ${errorText}`);
        throw new Error(`Token refresh failed: ${response.statusText}`);
      }

      const tokenData = await response.json();

      const encryptedAccessToken = this.encryptionService.encryptToString(tokenData.access_token);
      // Keep old refresh token if new one not provided
      const encryptedRefreshToken = this.encryptionService.encryptToString(
        tokenData.refresh_token || userProfile.refreshToken,
      );

      // Update the stored tokens
      await this.drizzle
        .update(userProfiles)
        .set({
          accessToken: encryptedAccessToken,
          refreshToken: encryptedRefreshToken,
        })
        .where(eq(userProfiles.id, userProfileId));

      this.logger.debug(`Successfully refreshed token for user ${this.userProfileId}`);
      return tokenData.access_token;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to refresh token for user',
        error: serializeError(normalizeError(error)),
      });
      throw new Error(
        `Token refresh failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
      );
    }
  }
}
