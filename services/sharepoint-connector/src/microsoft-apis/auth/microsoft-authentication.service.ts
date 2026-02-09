import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { ProxyService } from '../../proxy';
import { AuthStrategy } from './strategies/auth-strategy.interface';
import { CertificateAuthStrategy } from './strategies/certificate-auth.strategy';
import { ClientSecretAuthStrategy } from './strategies/client-secret-auth.strategy';
import { TokenCache } from './token-cache';
import { AuthenticationScope } from './types';

/**
 * Microsoft Authentication Provider.
 * Uses strategy pattern to support different authentication methods:
 * - Client Secret Strategy (for local development)
 * - Client Certificate (for Sharepoint REST V1 API access)
 */
@Injectable()
export class MicrosoftAuthenticationService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly strategy: AuthStrategy;

  private readonly scopesMap: Record<AuthenticationScope, string[]>;
  private readonly tokensCache: Record<AuthenticationScope, TokenCache> = {
    [AuthenticationScope.GRAPH]: new TokenCache(),
    [AuthenticationScope.SHAREPOINT_REST]: new TokenCache(),
  };

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly proxyService: ProxyService,
  ) {
    this.scopesMap = {
      [AuthenticationScope.GRAPH]: ['https://graph.microsoft.com/.default'],
      [AuthenticationScope.SHAREPOINT_REST]: [
        `${this.configService.get('sharepoint.baseUrl', { infer: true })}/.default`,
      ],
    };

    const dispatcher = this.proxyService.getDispatcher({ mode: 'always' });
    const authMode = this.configService.get('sharepoint.auth.mode', { infer: true });
    switch (authMode) {
      case 'client-secret':
        this.strategy = new ClientSecretAuthStrategy(configService, dispatcher);
        break;
      case 'certificate':
        this.strategy = new CertificateAuthStrategy(configService, dispatcher);
        break;
      default:
        throw new Error(`Unsupported authentication mode: ${authMode}`);
    }
    this.logger.log(`Using ${this.strategy.constructor.name} for Microsoft API authentication`);
  }

  public async getAccessToken(scope: AuthenticationScope): Promise<string> {
    return await this.tokensCache[scope].getToken(() =>
      this.strategy.acquireNewToken(this.scopesMap[scope]),
    );
  }
}
