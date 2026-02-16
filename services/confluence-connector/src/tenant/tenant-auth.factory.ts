import { Injectable, Logger } from '@nestjs/common';
import { AuthMode, type ConfluenceConfig } from '../config/confluence.schema';
import type { ConfluenceAuthStrategy } from '../confluence-auth/strategies/confluence-auth-strategy.interface';
import { OAuth2LoAuthStrategy } from '../confluence-auth/strategies/oauth2lo-auth.strategy';
import { PatAuthStrategy } from '../confluence-auth/strategies/pat-auth.strategy';
import { TokenCache } from '../confluence-auth/token-cache';
import type { TenantAuth } from './tenant-auth.interface';

@Injectable()
export class TenantAuthFactory {
  private readonly logger = new Logger(TenantAuthFactory.name);

  public create(confluenceConfig: ConfluenceConfig): TenantAuth {
    const strategy = this.createAuthStrategy(confluenceConfig);
    const tokenCache = new TokenCache();
    return {
      getAccessToken: () => tokenCache.getToken(() => strategy.acquireToken()),
    };
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
        const exhaustive: never = config.auth;
        throw new Error(`Unsupported auth mode: ${(exhaustive as { mode: string }).mode}`);
      }
    }
  }
}
