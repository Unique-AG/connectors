import * as assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { request } from 'undici';
import { Config } from '../config';
import { normalizeError } from '../utils/normalize-error';
import { ZitadelLoginResponse } from './unique-api.types';

@Injectable()
export class UniqueAuthService {
  private readonly logger = new Logger(this.constructor.name);
  protected cachedToken?: string;
  private tokenExpirationTime?: number;

  public constructor(private readonly configService: ConfigService<Config, true>) {}

  public async getToken(): Promise<string> {
    if (this.isTokenValid()) {
      return this.cachedToken;
    }

    const oAuthTokenUrl = this.configService.get('uniqueApi.zitadelOAuthTokenUrl', { infer: true });
    const clientId = this.configService.get('uniqueApi.zitadelClientId', { infer: true });
    const clientSecret = this.configService.get('uniqueApi.zitadelClientSecret', { infer: true });
    const projectId = this.configService.get('uniqueApi.zitadelProjectId', { infer: true });
    const params = new URLSearchParams({
      scope:
        `openid profile email urn:zitadel:iam:user:resourceowner ` +
        `urn:zitadel:iam:org:projects:roles urn:zitadel:iam:org:project:id:${projectId}:aud`,
      grant_type: 'client_credentials',
    });

    try {
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

      const tokenData = (await body.json()) as ZitadelLoginResponse;
      assert.ok(tokenData.access_token, 'Invalid token response: missing access_token');

      this.cachedToken = tokenData.access_token;
      this.tokenExpirationTime = Date.now() + tokenData.expires_in * 1000;
      return tokenData.access_token;
    } catch (error) {
      const normalized = normalizeError(error);
      this.logger.error('Failed to acquire Unique API token from Zitadel:', normalized.message);
      throw error;
    }
  }

  private isTokenValid(): this is this & { cachedToken: string } {
    return Boolean(
      this.cachedToken !== null &&
        this.tokenExpirationTime &&
        Date.now() < this.tokenExpirationTime,
    );
  }
}
