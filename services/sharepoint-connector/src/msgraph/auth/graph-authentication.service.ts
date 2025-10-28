import { AuthenticationProvider } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { CertificateGraphAuthStrategy } from './certificate-graph-auth-startegy';
import { ClientSecretGraphAuthStrategy } from './client-secret-graph-auth.strategy';
import { GraphAuthStrategy } from './graph-auth-strategy.interface';
import { OidcGraphAuthStrategy } from './oidc-graph-auth.strategy';

/**
 * Microsoft Graph Authentication Provider.
 * Uses strategy pattern to support different authentication methods:
 * - Client Secret Strategy (for local development)
 * - OIDC/Workload Identity Strategy (for AKS deployment)
 * - Client Certificate (for Sharepoint REST V1 API access)
 */
@Injectable()
export class GraphAuthenticationService implements AuthenticationProvider {
  private readonly logger = new Logger(this.constructor.name);
  private readonly strategy: GraphAuthStrategy;

  public constructor(private readonly configService: ConfigService<Config, true>) {
    switch (this.configService.get('sharepoint.authMode', { infer: true })) {
      case 'oidc':
        this.strategy = new OidcGraphAuthStrategy(configService);
        break;
      case 'client-secret':
        this.strategy = new ClientSecretGraphAuthStrategy(configService);
        break;
      case 'certificate':
        this.strategy = new CertificateGraphAuthStrategy(configService);
        break;
    }
    this.logger.log(`Using ${this.strategy.constructor.name} for Graph API authentication`);
  }

  public async getAccessToken(): Promise<string> {
    return await this.strategy.getAccessToken();
  }
}
