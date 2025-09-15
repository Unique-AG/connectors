import {
  AuthenticationResult,
  type ClientCredentialRequest,
  ConfidentialClientApplication,
  type Configuration,
} from '@azure/msal-node';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { IAuthProvider } from './auth-provider.interface';

@Injectable()
export class SharepointAuthService implements IAuthProvider {
  private readonly logger = new Logger(this.constructor.name);
  private readonly msalClient: ConfidentialClientApplication;

  public constructor(private readonly configService: ConfigService) {
    const tenantId = this.configService.get<string>('sharepoint.tenantId') ?? '';
    const msalConfig: Configuration = {
      auth: {
        clientId: this.configService.get<string>('sharepoint.clientId', ''),
        authority: `https://login.microsoftonline.com/${tenantId}`,
        clientSecret: this.configService.get<string>('sharepoint.clientSecret', ''),
      },
    };
    this.msalClient = new ConfidentialClientApplication(msalConfig);
  }

  public async getToken(_forceRefresh = false): Promise<string> {
    this.logger.debug('Acquiring new Microsoft Graph API token...');

    const tokenRequest: ClientCredentialRequest = {
      scopes: ['https://graph.microsoft.com/.default'],
    };

    try {
      const response = await this.msalClient.acquireTokenByClientCredential(tokenRequest);
      if (!response?.accessToken) {
        throw new Error('Failed to acquire Graph API token: no access token in response');
      }

      this.logger.debug('Successfully acquired new Microsoft Graph API token.');
      return response.accessToken;
    } catch (error) {
      this.logger.error('Failed to acquire Graph API token', error as Error);
      throw error;
    }
  }
}
