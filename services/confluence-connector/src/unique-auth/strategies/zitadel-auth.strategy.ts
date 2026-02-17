import { Logger } from '@nestjs/common';
import { Agent, type Dispatcher, interceptors } from 'undici';
import type { UniqueConfig } from '../../config/unique.schema';
import { TokenCache } from '../../confluence-auth/token-cache';
import { sanitizeError } from '../../utils/normalize-error';
import { UniqueServiceAuth } from '../unique-service-auth';

type ExternalConfig = Extract<UniqueConfig, { serviceAuthMode: 'external' }>;

interface ZitadelTokenResponse {
  access_token: string;
  expires_in: number;
  token_type: string;
}

export class ZitadelAuthStrategy extends UniqueServiceAuth {
  private readonly logger = new Logger(ZitadelAuthStrategy.name);
  private readonly tokenCache: TokenCache;
  private readonly agent: Agent;
  private readonly dispatcher: Dispatcher;
  private readonly tokenUrl: string;
  private readonly basicAuth: string;
  private readonly scope: string;

  public constructor(config: ExternalConfig) {
    super();
    this.tokenCache = new TokenCache();
    this.agent = new Agent();
    this.dispatcher = this.agent.compose(interceptors.retry(), interceptors.redirect());
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
      const url = new URL(this.tokenUrl);
      const { statusCode, body: responseBody } = await this.dispatcher.request({
        origin: url.origin,
        path: url.pathname + url.search,
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          Authorization: `Basic ${this.basicAuth}`,
        },
        body: body.toString(),
      });

      if (statusCode < 200 || statusCode >= 300) {
        const errorText = await responseBody.text().catch(() => 'No response body');
        throw new Error(
          `Zitadel token request failed with status ${statusCode}. ` +
            `URL: ${this.tokenUrl}, Response: ${errorText}`,
        );
      }

      const tokenData = (await responseBody.json()) as ZitadelTokenResponse;
      if (!tokenData.access_token) {
        throw new Error('Invalid token response: missing access_token');
      }

      return {
        accessToken: tokenData.access_token,
        expiresAt: new Date(Date.now() + tokenData.expires_in * 1000),
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to acquire Unique API token from Zitadel',
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  public async close(): Promise<void> {
    await this.agent.close();
  }
}
