import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { BaseClient, Issuer, TokenSet } from 'openid-client';
import * as z from 'zod';
import { AppConfig, AppSettings } from '../app-settings.enum';

const FACTSET_WELL_KNOWN_URL = 'https://auth.factset.com/.well-known/openid-configuration';

const factsetConfigSchema = z.object({
  name: z.string(),
  clientId: z.string(),
  clientAuthType: z.string(),
  owners: z.array(z.string()),
  wellKnownUri: z.url().prefault(FACTSET_WELL_KNOWN_URL),
  jwk: z.object({
    kty: z.string(),
    use: z.string(),
    alg: z.string(),
    kid: z.string(),
    d: z.string(),
    n: z.string(),
    e: z.string(),
    p: z.string(),
    q: z.string(),
    dp: z.string(),
    dq: z.string(),
    qi: z.string(),
  }),
});
type FactsetConfig = z.infer<typeof factsetConfigSchema>;

@Injectable()
export class FactsetClientCredentials implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);
  private readonly config: FactsetConfig;
  private oauthClient: BaseClient | undefined;
  private tokenSet: TokenSet | undefined;

  public constructor(configService: ConfigService<AppConfig, true>) {
    this.config = factsetConfigSchema.parse(configService.get(AppSettings.FACTSET_AUTH_CONFIG));
  }

  public async onModuleInit(): Promise<void> {
    try {
      const issuer = await Issuer.discover(this.config.wellKnownUri);
      this.oauthClient = new issuer.Client(
        {
          client_id: this.config.clientId,
          token_endpoint_auth_method: 'private_key_jwt',
        },
        {
          keys: [this.config.jwk],
        },
      );
    } catch (_error) {
      throw new Error(
        `Failed to discover FactSet OAuth2 issuer from well-known URL: ${this.config.wellKnownUri}`,
      );
    }

    // Eagerly fetch the access token to avoid delay when it's needed
    this.getAccessToken();
  }

  /**
   * Returns an access token that can be used for authentication.
   *
   * If the cache contains a valid access token, it's returned. Otherwise
   * a new access token is retrieved from FactSet's authorization server.
   *
   * The access token should be used immediately and not stored to avoid
   * any issues with token expiry.
   *
   * The access token is used in the Authorization header when when accessing
   * FactSet's APIs. Example: `{"Authorization": "Bearer access-token"}`
   *
   * @returns access token for protected resource requests
   */
  public async getAccessToken(): Promise<string> {
    if (this.tokenSet && !this.isTokenSetExpired()) {
      // biome-ignore lint/style/noNonNullAssertion: We check for the presence of the access token in the token set
      return this.tokenSet.access_token!;
    }

    this.logger.debug({
      msg: 'No Factset token or token is expired. Fetching new one.',
      expiredAt: this.tokenSet?.expires_at,
    });

    await this.fetchAccessToken();
    // biome-ignore lint/style/noNonNullAssertion: We check for the presence of tokenSet and access token in the fetchAccessToken method
    return this.tokenSet!.access_token!;
  }

  private async fetchAccessToken(): Promise<void> {
    if (!this.oauthClient) {
      throw new Error('OAuth client not initialized');
    }

    // Factset returns
    // {
    //   "access_token": "eyJhbGc...",
    //   "token_type": "Bearer",
    //   "expires_at": 1719734400
    // }
    const tokenSet = await this.oauthClient.grant({
      grant_type: 'client_credentials',
    });

    if (!tokenSet.access_token || typeof tokenSet.access_token !== 'string') {
      throw new Error('No access token returned from FactSet');
    }
    if (!tokenSet.expires_at || typeof tokenSet.expires_at !== 'number') {
      throw new Error('No expires_at returned from FactSet');
    }
    if (!tokenSet.token_type || tokenSet.token_type !== 'Bearer') {
      throw new Error('Invalid token type returned from FactSet');
    }

    this.tokenSet = tokenSet;
  }

  private isTokenSetExpired(): boolean {
    if (!this.tokenSet) {
      return true;
    }
    if (!this.tokenSet.expires_at) {
      return true;
    }
    return this.tokenSet.expires_at < Date.now() / 1000;
  }
}
