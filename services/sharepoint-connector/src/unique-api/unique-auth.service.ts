import * as assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { HttpClientService } from '../shared/services/http-client.service';
import { sanitizeError } from '../utils/normalize-error';

@Injectable()
export class UniqueAuthService {
  private readonly logger = new Logger(this.constructor.name);
  // used protected to allow use of typeguard isTokenValid
  protected cachedToken?: string;
  private tokenExpirationTime?: number;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly httpClientService: HttpClientService,
  ) {}

  public async getToken(): Promise<string> {
    if (this.isTokenValid()) {
      return this.cachedToken;
    }

    const uniqueConfig = this.configService.get('unique', { infer: true });
    assert.strictEqual(
      uniqueConfig.serviceAuthMode,
      'external',
      'UniqueAuthService called but serviceAuthMode is not "external"',
    );

    const { zitadelOauthTokenUrl, zitadelClientId, zitadelClientSecret, zitadelProjectId } =
      uniqueConfig;

    const params = new URLSearchParams({
      scope:
        `openid profile email urn:zitadel:iam:user:resourceowner ` +
        `urn:zitadel:iam:org:projects:roles urn:zitadel:iam:org:project:id:${zitadelProjectId}:aud`,
      grant_type: 'client_credentials',
    });

    try {
      const basicAuth = Buffer.from(`${zitadelClientId}:${zitadelClientSecret.value}`).toString(
        'base64',
      );
      const { statusCode, body } = await this.httpClientService.request(zitadelOauthTokenUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          Authorization: `Basic ${basicAuth}`,
        },
        body: params.toString(),
      });

      if (statusCode < 200 || statusCode >= 300) {
        const errorText = await body.text().catch(() => 'No response body');
        throw new Error(
          `Zitadel token request failed with status ${statusCode}. ` +
            `URL: ${zitadelOauthTokenUrl}, Response: ${errorText}`,
        );
      }

      const tokenData = (await body.json()) as ZitadelLoginResponse;
      assert.ok(tokenData.access_token, 'Invalid token response: missing access_token');

      this.cachedToken = tokenData.access_token;
      this.tokenExpirationTime = Date.now() + tokenData.expires_in * 1000;
      return tokenData.access_token;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to acquire Unique API token from Zitadel',
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  private isTokenValid(): this is this & { cachedToken: string } {
    return Boolean(
      this.cachedToken && this.tokenExpirationTime && Date.now() < this.tokenExpirationTime,
    );
  }
}

interface ZitadelLoginResponse {
  access_token: string;
  expires_in: number;
  token_type: string;
  id_token: string;
}
