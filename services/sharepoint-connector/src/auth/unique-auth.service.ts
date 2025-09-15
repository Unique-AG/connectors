import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Client } from 'undici';
import { UNIQUE_HTTP_CLIENT } from '../http-client.tokens';
import type { IAuthProvider } from './auth-provider.interface';
import { isTokenExpiringSoon } from './token-utils';

@Injectable()
export class UniqueAuthService implements IAuthProvider {
  private readonly logger = new Logger(this.constructor.name);
  private tokenCache: { accessToken: string; expiresOn: number; acquiredAt: number } | null = null;

  public constructor(
    private readonly configService: ConfigService,
    @Inject(UNIQUE_HTTP_CLIENT) private readonly httpClient: Client,
  ) {}

  public async getToken(forceRefresh = false): Promise<string> {
    if (!forceRefresh && !isTokenExpiringSoon(this.tokenCache?.expiresOn)) {
      const cached = this.tokenCache?.accessToken;
      if (cached) return cached;
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

      const now = Date.now();
      const url = new URL(oAuthTokenUrl);
      const path = url.pathname + url.search;

      const { body } = await this.httpClient.request({
        method: 'POST',
        path,
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString('base64')}`,
        },
        body: params.toString(),
        throwOnError: true,
      });

      const tokenData = (await body.json()) as {
        access_token: string;
        expires_in: number;
        token_type: string;
        id_token: string;
      };

      if (!tokenData.access_token) {
        throw new Error('Invalid token response: missing access_token');
      }

      const expiresAt = now + tokenData.expires_in * 1000;
      this.tokenCache = {
        accessToken: tokenData.access_token,
        expiresOn: expiresAt,
        acquiredAt: now,
      };
      this.logger.debug(
        `Successfully acquired new Zitadel token that expires in ${String(
          tokenData.expires_in,
        )} seconds at ${new Date(expiresAt).toISOString()}`,
      );

      return this.tokenCache.accessToken;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.logger.error('Failed to acquire Unique API token from Zitadel:', errorMessage);
      throw error;
    }
  }
}
