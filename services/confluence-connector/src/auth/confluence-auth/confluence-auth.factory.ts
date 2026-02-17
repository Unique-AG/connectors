import { Injectable } from '@nestjs/common';
import { AuthMode, type ConfluenceConfig } from '../../config';
import { ServiceRegistry } from '../../tenant';
import { ConfluenceAuth } from './confluence-auth.abstract';
import { OAuth2LoAuthStrategy } from './strategies/oauth2lo-auth.strategy';
import { PatAuthStrategy } from './strategies/pat-auth.strategy';

@Injectable()
export class ConfluenceAuthFactory {
  public constructor(private readonly serviceRegistry: ServiceRegistry) {}

  public createAuthStrategy(config: ConfluenceConfig): ConfluenceAuth {
    const logger = this.serviceRegistry.getServiceLogger(ConfluenceAuthFactory);
    switch (config.auth.mode) {
      case AuthMode.OAUTH_2LO: {
        logger.info(`Using OAuth 2.0 2LO authentication for ${config.instanceType} instance`);
        return new OAuth2LoAuthStrategy(config.auth, config, this.serviceRegistry);
      }
      case AuthMode.PAT: {
        logger.info('Using PAT authentication for data-center instance');
        return new PatAuthStrategy(config.auth);
      }
      default: {
        throw new Error(`Unsupported Confluence auth mode`);
      }
    }
  }
}
