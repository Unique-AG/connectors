import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { AuthStrategy } from './strategies/auth-strategy.interface';
import { CertificateAuthStrategy } from './strategies/certificate-auth.strategy';
import { ClientSecretAuthStrategy } from './strategies/client-secret-auth.strategy';
import { OidcAuthStrategy } from './strategies/oidc-auth.strategy';
import { TokenCache } from './token-cache';
import { AuthenticationScope } from './types';

/**
 * Microsoft Authentication Provider.
 * Uses strategy pattern to support different authentication methods:
 * - Client Secret Strategy (for local development)
 * - OIDC/Workload Identity Strategy (for AKS deployment)
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

  public constructor(private readonly configService: ConfigService<Config, true>) {
    this.scopesMap = {
      [AuthenticationScope.GRAPH]: ['https://graph.microsoft.com/.default'],
      [AuthenticationScope.SHAREPOINT_REST]: [
        `${this.configService.get('sharepoint.baseUrl', { infer: true })}/.default`,
      ],
    };

    switch (this.configService.get('sharepoint.authMode', { infer: true })) {
      case 'oidc':
        this.strategy = new OidcAuthStrategy(configService);
        break;
      case 'client-secret':
        this.strategy = new ClientSecretAuthStrategy(configService);
        break;
      case 'certificate':
        this.strategy = new CertificateAuthStrategy(configService);
        break;
    }
    this.logger.log(`Using ${this.strategy.constructor.name} for Microsoft API authentication`);
  }

  public async getAccessToken(scope: AuthenticationScope): Promise<string> {
    return await this.tokensCache[scope].getToken(() =>
      this.strategy.acquireNewToken(this.scopesMap[scope]),
    );
  }
}
