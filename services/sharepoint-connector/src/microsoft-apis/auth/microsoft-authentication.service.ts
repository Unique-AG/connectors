import { AuthenticationProvider } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { AuthStrategy } from './auth-strategy.interface';
import { CertificateAuthStrategy } from './certificate-auth.strategy';
import { ClientSecretAuthStrategy } from './client-secret-auth.strategy';
import { OidcAuthStrategy } from './oidc-auth.strategy';

/**
 * Microsoft Authentication Provider.
 * Uses strategy pattern to support different authentication methods:
 * - Client Secret Strategy (for local development)
 * - OIDC/Workload Identity Strategy (for AKS deployment)
 * - Client Certificate (for Sharepoint REST V1 API access)
 */
@Injectable()
export class MicrosoftAuthenticationService implements AuthenticationProvider {
  private readonly logger = new Logger(this.constructor.name);
  private readonly strategy: AuthStrategy;

  public constructor(private readonly configService: ConfigService<Config, true>) {
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

  public async getAccessToken(): Promise<string> {
    return await this.strategy.getAccessToken();
  }
}
