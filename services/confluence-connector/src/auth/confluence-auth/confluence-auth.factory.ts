import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import type { Dispatcher } from 'undici';
import { AuthMode, type ConfluenceConfig } from '../../config';
import { ProxyService } from '../../proxy';
import { getCurrentTenant } from '../../tenant/tenant-context.storage';
import { ConfluenceAuth } from './confluence-auth.abstract';
import { OAuth2LoAuthStrategy } from './strategies/oauth2lo-auth.strategy';
import { PatAuthStrategy } from './strategies/pat-auth.strategy';

@Injectable()
export class ConfluenceAuthFactory {
  private readonly logger = new Logger(ConfluenceAuthFactory.name);
  private readonly dispatcher: Dispatcher;

  public constructor(proxyService: ProxyService) {
    this.dispatcher = proxyService.getDispatcher({ mode: 'always' });
  }

  public createAuthStrategy(config: ConfluenceConfig): ConfluenceAuth {
    // Explicitly read tenantName because this runs during onModuleInit, before
    // main.ts swaps in the pino logger — the mixin that auto-injects tenantName
    // into logs is not active yet at this point.
    const { name: tenantName } = getCurrentTenant();
    switch (config.auth.mode) {
      case AuthMode.OAuth2Lo: {
        this.logger.log({
          tenantName,
          msg: `Using OAuth 2.0 2LO authentication for ${config.instanceType} instance`,
        });
        return new OAuth2LoAuthStrategy(config.auth, config, this.dispatcher);
      }
      case AuthMode.Pat: {
        this.logger.log({ tenantName, msg: 'Using PAT authentication for data-center instance' });
        return new PatAuthStrategy(config.auth);
      }
      default: {
        assert.fail(`Unsupported Confluence auth mode`);
      }
    }
  }
}
