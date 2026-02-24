import { request } from 'undici';
import { z } from 'zod';
import { AuthMode, ConfluenceConfig } from '../../../config';
import { ServiceRegistry } from '../../../tenant/service-registry';
import { handleErrorStatus } from '../../../utils/http-util';
import { TokenCache } from '../../token-cache';
import type { TokenResult } from '../../token-result';
import { ConfluenceAuth } from '../confluence-auth.abstract';

type OAuth2LoAuthConfig = Extract<ConfluenceConfig['auth'], { mode: typeof AuthMode.OAUTH_2LO }>;
interface OAuth2LoConnectionConfig {
  instanceType: 'cloud' | 'data-center';
  baseUrl: string;
}

// Centralized Atlassian identity endpoint — same for all Cloud tenants
const CLOUD_TOKEN_ENDPOINT = 'https://api.atlassian.com/oauth/token';

// Data Center service accounts require an explicit scope in the token request
const DC_TOKEN_SCOPE = 'READ';

const tokenResponseSchema = z.object({
  access_token: z.string(),
  expires_in: z.number(),
});

export class OAuth2LoAuthStrategy extends ConfluenceAuth {
  private readonly serviceRegistry: ServiceRegistry;
  private readonly tokenCache = new TokenCache();
  private readonly clientId: string;
  private readonly clientSecret: string;
  private readonly tokenEndpoint: string;
  private readonly instanceType: 'cloud' | 'data-center';

  public constructor(
    authConfig: OAuth2LoAuthConfig,
    connectionConfig: OAuth2LoConnectionConfig,
    serviceRegistry: ServiceRegistry,
  ) {
    super();
    this.serviceRegistry = serviceRegistry;
    this.clientId = authConfig.clientId;
    this.clientSecret = authConfig.clientSecret.value;
    this.instanceType = connectionConfig.instanceType;
    this.tokenEndpoint =
      connectionConfig.instanceType === 'cloud'
        ? CLOUD_TOKEN_ENDPOINT
        : `${connectionConfig.baseUrl}/rest/oauth2/latest/token`;
  }

  public async acquireToken(): Promise<string> {
    return this.tokenCache.getToken(() => this.fetchToken());
  }

  private async fetchToken(): Promise<TokenResult> {
    const logger = this.serviceRegistry.getServiceLogger(OAuth2LoAuthStrategy);
    logger.info(`Acquiring Confluence ${this.instanceType} token via OAuth 2.0 2LO`);

    try {
      return await this.requestToken();
    } catch (error) {
      logger.error({
        msg: `Failed to acquire Confluence ${this.instanceType} token via OAuth 2.0 2LO`,
        error,
      });

      throw error;
    }
  }

  private async requestToken(): Promise<TokenResult> {
    const { headers, body } = this.buildRequest();

    const response = await request(this.tokenEndpoint, { method: 'POST', headers, body });

    await handleErrorStatus(response.statusCode, response.body, this.tokenEndpoint);

    const tokenBody = await response.body.json();
    const { access_token, expires_in } = tokenResponseSchema.parse(tokenBody);

    return {
      accessToken: access_token,
      expiresAt: new Date(Date.now() + expires_in * 1000),
    };
  }

  private buildRequest(): { headers: Record<string, string>; body: string } {
    const payload = {
      grant_type: 'client_credentials',
      client_id: this.clientId,
      client_secret: this.clientSecret,
    };

    if (this.instanceType === 'cloud') {
      return {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      };
    }

    return {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ ...payload, scope: DC_TOKEN_SCOPE }).toString(),
    };
  }
}
