import { Inject, Injectable, Logger, OnModuleInit } from '@nestjs/common';
import passport from 'passport';
import { OAUTH_ENDPOINTS } from '../constants/oauth.constants';
import { OAuthUserProfile } from '../interfaces/oauth-provider.interface';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';

export const STRATEGY_NAME = 'oauth-provider';

export interface PassportUser {
  profile: OAuthUserProfile;
  accessToken: string;
  refreshToken: string;
  provider: string;
}

@Injectable()
export class OAuthStrategyService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: McpOAuthModuleOptions,
  ) {}

  public onModuleInit() {
    this.registerStrategy();
  }

  private registerStrategy() {
    this.logger.log({
      msg: 'Registering OAuth strategy',
      provider: this.options.provider.name,
      clientId: this.options.clientId,
      serverUrl: this.options.serverUrl,
    });

    const provider = this.options.provider;

    const strategyOptions = provider.strategyOptions({
      serverUrl: this.options.serverUrl,
      clientId: this.options.clientId,
      clientSecret: this.options.clientSecret,
      callbackPath: OAUTH_ENDPOINTS.callback,
    });

    const strategy = new provider.strategy(
      strategyOptions,
      async (
        accessToken: string,
        refreshToken: string,
        profile: unknown,
        done: (error: unknown, user: unknown) => void,
      ) => {
        try {
          if (provider.validateCallback) {
            await provider.validateCallback(accessToken, refreshToken, profile);
          }
          const mappedProfile = provider.profileMapper(profile);
          const result: PassportUser = {
            profile: mappedProfile,
            accessToken,
            refreshToken,
            provider: provider.name,
          };

          done(null, result);
        } catch (error) {
          done(error, null);
        }
      },
    );

    passport.use(STRATEGY_NAME, strategy);
  }

  public getStrategyName(): string {
    return STRATEGY_NAME;
  }
}
