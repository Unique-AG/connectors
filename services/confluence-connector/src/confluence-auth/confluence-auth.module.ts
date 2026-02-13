import { Logger, Module } from '@nestjs/common';
import { AuthMode, type ConfluenceConfig, confluenceConfig } from '../config';
import { CONFLUENCE_AUTH_STRATEGY } from './confluence-auth.constants';
import { ConfluenceAuthenticationService } from './confluence-authentication.service';
import type { ConfluenceAuthStrategy } from './strategies/confluence-auth-strategy.interface';
import { OAuth2LoAuthStrategy } from './strategies/oauth2lo-auth.strategy';
import { PatAuthStrategy } from './strategies/pat-auth.strategy';

const logger = new Logger('ConfluenceAuthModule');

function createAuthStrategy(config: ConfluenceConfig): ConfluenceAuthStrategy {
  switch (config.auth.mode) {
    case AuthMode.OAUTH_2LO: {
      logger.log(`Using OAuth 2.0 2LO authentication for ${config.instanceType} instance`);
      return new OAuth2LoAuthStrategy(config.auth, config);
    }
    case AuthMode.PAT: {
      logger.log('Using PAT authentication for data-center instance');
      return new PatAuthStrategy(config.auth);
    }
  }
}

@Module({
  providers: [
    {
      provide: CONFLUENCE_AUTH_STRATEGY,
      useFactory: createAuthStrategy,
      inject: [confluenceConfig.KEY],
    },
    ConfluenceAuthenticationService,
  ],
  exports: [ConfluenceAuthenticationService],
})
export class ConfluenceAuthModule {}
