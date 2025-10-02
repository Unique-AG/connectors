import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { request } from 'undici';

@Injectable()
export class UniqueAuthService {
  private readonly logger = new Logger(this.constructor.name);
  private cachedToken: string | null = null;
  private tokenExpirationTime: number | null = null;

  public constructor(private readonly configService: ConfigService) {}

  public async getToken(forceRefresh = false): Promise<string> {
    if (!forceRefresh && this.isTokenValid()) {
      this.logger.debug('Using cached Zitadel token');
      return <string>this.cachedToken;
    }

    this.logger.debug('Acquiring new Unique API token from Zitadel...');
    try {
      const oAuthTokenUrl = <string>this.configService.get('uniqueApi.zitadelOAuthTokenUrl');
      const clientId = <string>this.configService.get('uniqueApi.zitadelClientId');
      const clientSecret = <string>this.configService.get('uniqueApi.zitadelClientSecret');
      const projectId = <string>this.configService.get('uniqueApi.zitadelProjectId');

      const params = new URLSearchParams({
        scope:
          `openid profile email urn:zitadel:iam:user:resourceowner ` +
          `urn:zitadel:iam:org:projects:roles urn:zitadel:iam:org:project:id:${projectId}:aud`,
        grant_type: 'client_credentials',
      });

      const { statusCode, body } = await request(oAuthTokenUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString('base64')}`,
        },
        body: params.toString(),
      });

      if (statusCode < 200 || statusCode >= 300) {
        const errorText = await body.text().catch(() => 'No response body');
        throw new Error(
          `Zitadel token request failed with status ${statusCode}. ` +
            `URL: ${oAuthTokenUrl}, Response: ${errorText}`,
        );
      }

      const tokenData = (await body.json()) as {
        access_token: string;
        expires_in: number;
        token_type: string;
        id_token: string;
      };

      if (!tokenData.access_token) {
        throw new Error('Invalid token response: missing access_token');
      }

      this.cachedToken = tokenData.access_token;
      this.tokenExpirationTime = Date.now() + tokenData.expires_in * 1000;

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
