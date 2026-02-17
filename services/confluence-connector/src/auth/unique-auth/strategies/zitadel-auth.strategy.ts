import assert from 'node:assert/strict';
import { request } from 'undici';
import { UniqueAuthMode, type UniqueConfig } from '../../../config';
import { ServiceRegistry } from '../../../tenant/service-registry';
import { handleErrorStatus } from '../../../utils/http-util';
import { sanitizeError } from '../../../utils/normalize-error';
import { TokenCache } from '../../token-cache';
import { UniqueAuth } from '../unique-auth.abstract';

type ExternalConfig = Extract<UniqueConfig, { serviceAuthMode: typeof UniqueAuthMode.EXTERNAL }>;

interface ZitadelTokenResponse {
  access_token: string;
  expires_in: number;
  token_type: string;
}

export class ZitadelAuthStrategy extends UniqueAuth {
  private readonly serviceRegistry: ServiceRegistry;
  private readonly tokenCache: TokenCache;
  private readonly tokenUrl: string;
  private readonly basicAuth: string;
  private readonly scope: string;

  public constructor(config: ExternalConfig, serviceRegistry: ServiceRegistry) {
    super();
    this.serviceRegistry = serviceRegistry;
    this.tokenCache = new TokenCache();
    this.tokenUrl = config.zitadelOauthTokenUrl;

    this.basicAuth = Buffer.from(
      `${config.zitadelClientId}:${config.zitadelClientSecret.value}`,
    ).toString('base64');

    this.scope =
      `openid profile email urn:zitadel:iam:user:resourceowner ` +
      `urn:zitadel:iam:org:projects:roles urn:zitadel:iam:org:project:id:${config.zitadelProjectId.value}:aud`;
  }

  public async getHeaders(): Promise<Record<string, string>> {
    const token = await this.tokenCache.getToken(() => this.acquireToken());
    return { Authorization: `Bearer ${token}` };
  }

  private async acquireToken(): Promise<{ accessToken: string; expiresAt?: Date }> {
    const body = new URLSearchParams({
      scope: this.scope,
      grant_type: 'client_credentials',
    });

    try {
      const { statusCode, body: responseBody } = await request(this.tokenUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          Authorization: `Basic ${this.basicAuth}`,
        },
        body: body.toString(),
      });

      await handleErrorStatus(statusCode, responseBody, this.tokenUrl);

      const tokenData = (await responseBody.json()) as ZitadelTokenResponse;
      assert.ok(tokenData.access_token, 'Invalid token response: missing access_token');

      return {
        accessToken: tokenData.access_token,
        expiresAt: new Date(Date.now() + tokenData.expires_in * 1000),
      };
    } catch (error) {
      const logger = this.serviceRegistry.getServiceLogger(ZitadelAuthStrategy);
      logger.error({
        msg: 'Failed to acquire Unique API token from Zitadel',
        error: sanitizeError(error),
      });
      throw error;
    }
  }
}
