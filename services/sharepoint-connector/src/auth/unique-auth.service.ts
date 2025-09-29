import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { IAuthProvider } from './auth-provider.interface';

@Injectable()
export class UniqueAuthService implements IAuthProvider {
  private readonly logger = new Logger(this.constructor.name);
  private cachedToken: string | null = null;
  private tokenExpirationTime: number | null = null;

  public constructor(
    private readonly configService: ConfigService,
  ) {}

  public async getToken(forceRefresh = false): Promise<string> {
    if (!forceRefresh && this.isTokenValid()) {
      this.logger.debug('Using cached Zitadel token');
      return this.cachedToken as string;
    }

    this.logger.debug('Acquiring new Unique API token from Zitadel...');
    try {
      const oAuthTokenUrl = this.configService.get<string>('uniqueApi.zitadelOAuthTokenUrl') ?? '';
      const clientId = this.configService.get<string>('uniqueApi.zitadelClientId') ?? '';
      const clientSecret = this.configService.get<string>('uniqueApi.zitadelClientSecret') ?? '';
      const projectId = (
        this.configService.get<string>('uniqueApi.zitadelProjectId') ?? ''
      ).replace(/\D/g, '');

      const params = new URLSearchParams({
        scope:
          `openid profile email urn:zitadel:iam:user:resourceowner ` +
          `urn:zitadel:iam:org:projects:roles urn:zitadel:iam:org:project:id:${projectId}:aud`,
        grant_type: 'client_credentials',
      });

      const response = await fetch(oAuthTokenUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString('base64')}`,
        },
        body: params.toString(),
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => 'No response body');
        throw new Error(
          `Zitadel token request failed with status ${response.status}. ` +
            `URL: ${oAuthTokenUrl}, Response: ${errorText}`,
        );
      }

      const tokenData = (await response.json()) as {
        access_token: string;
        expires_in: number;
        token_type: string;
        id_token: string;
      };

      if (!tokenData.access_token) {
        throw new Error('Invalid token response: missing access_token');
      }

      // Cache the token and calculate expiration time
      this.cachedToken = tokenData.access_token;
      this.tokenExpirationTime = Date.now() + (tokenData.expires_in * 1000);

      this.logger.debug(`Successfully acquired and cached new Zitadel token`);
      return tokenData.access_token;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.logger.error('Failed to acquire Unique API token from Zitadel:', errorMessage);
      throw error;
    }
  }

  private isTokenValid(): boolean {
    return (
      this.cachedToken !== null &&
      this.tokenExpirationTime !== null &&
      Date.now() < this.tokenExpirationTime
    );
  }
}
