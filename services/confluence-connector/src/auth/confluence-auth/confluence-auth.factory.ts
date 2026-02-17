import { Injectable, Logger } from '@nestjs/common';
import { AuthMode, type ConfluenceConfig } from '../../config';
import { TokenCache } from '../token-cache';
import type { ConfluenceAuthStrategy } from './strategies/confluence-auth-strategy.interface';
import { OAuth2LoAuthStrategy } from './strategies/oauth2lo-auth.strategy';
import { PatAuthStrategy } from './strategies/pat-auth.strategy';

export abstract class ConfluenceAuth {
  public abstract getAccessToken(): Promise<string>;
}

class CachedConfluenceAuth extends ConfluenceAuth {
  public constructor(
    private readonly strategy: ConfluenceAuthStrategy,
    private readonly tokenCache: TokenCache,
  ) {
    super();
  }

  public async getAccessToken(): Promise<string> {
    return this.tokenCache.getToken(() => this.strategy.acquireToken());
  }
}

@Injectable()
export class ConfluenceAuthFactory {
  private readonly logger = new Logger(ConfluenceAuthFactory.name);

  public create(confluenceConfig: ConfluenceConfig): ConfluenceAuth {
    const strategy = this.createAuthStrategy(confluenceConfig);
    const tokenCache = new TokenCache();

    return new CachedConfluenceAuth(strategy, tokenCache);
  }

  private createAuthStrategy(config: ConfluenceConfig): ConfluenceAuthStrategy {
    switch (config.auth.mode) {
      case AuthMode.OAUTH_2LO: {
        this.logger.log(`Using OAuth 2.0 2LO authentication for ${config.instanceType} instance`);
        return new OAuth2LoAuthStrategy(config.auth, config);
      }
      case AuthMode.PAT: {
        this.logger.log('Using PAT authentication for data-center instance');
        return new PatAuthStrategy(config.auth);
      }
      default: {
        throw new Error(`Unsupported Confluence auth mode`);
      }
    }
  }
}
