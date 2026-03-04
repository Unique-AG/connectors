import { Injectable, Logger } from '@nestjs/common';
import { AuthMode, type ConfluenceConfig } from '../../config';
import { getCurrentTenant } from '../../tenant/tenant-context.storage';
import { ConfluenceAuth } from './confluence-auth.abstract';
import { OAuth2LoAuthStrategy } from './strategies/oauth2lo-auth.strategy';
import { PatAuthStrategy } from './strategies/pat-auth.strategy';

@Injectable()
export class ConfluenceAuthFactory {
  private readonly logger = new Logger(ConfluenceAuthFactory.name);

  public createAuthStrategy(config: ConfluenceConfig): ConfluenceAuth {
    const { name: tenantName } = getCurrentTenant();
    switch (config.auth.mode) {
      case AuthMode.OAUTH_2LO: {
        this.logger.log({ tenantName, msg: `Using OAuth 2.0 2LO authentication for ${config.instanceType} instance` });
        return new OAuth2LoAuthStrategy(config.auth, config);
      }
      case AuthMode.PAT: {
        this.logger.log({ tenantName, msg: 'Using PAT authentication for data-center instance' });
        return new PatAuthStrategy(config.auth);
      }
      default: {
        throw new Error(`Unsupported Confluence auth mode`);
      }
    }
  }
}
