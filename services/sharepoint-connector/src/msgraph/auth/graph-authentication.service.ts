import { AuthenticationProvider } from '@microsoft/microsoft-graph-client';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { ClientSecretGraphAuthStrategy } from './client-secret-graph-auth.strategy';
import { GraphAuthStrategy } from './graph-auth-strategy.interface';
import { OidcGraphAuthStrategy } from './oidc-graph-auth.strategy';

/**
 * Microsoft Graph Authentication Provider.
 * Uses strategy pattern to support different authentication methods:
 * - Client Secret Strategy (for local development)
 * - OIDC/Workload Identity Strategy (for AKS deployment)
 */
@Injectable()
export class GraphAuthenticationService implements AuthenticationProvider {
  private readonly strategy: GraphAuthStrategy;

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const useOidc = this.configService.get('sharepoint.graphUseOidcAuth', { infer: true });

    if (useOidc) {
      this.strategy = new OidcGraphAuthStrategy(configService);
    } else {
      this.strategy = new ClientSecretGraphAuthStrategy(configService);
    }
  }

  public async getAccessToken(): Promise<string> {
    return await this.strategy.getAccessToken('https://graph.microsoft.com/.default');
  }
}
