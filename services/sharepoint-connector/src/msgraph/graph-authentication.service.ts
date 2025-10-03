import {
  AuthenticationResult,
  type ClientCredentialRequest,
  ConfidentialClientApplication,
  type Configuration,
} from '@azure/msal-node';
import {
  AuthenticationProvider,
  AuthenticationProviderOptions,
} from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { serializeError } from 'serialize-error-cjs';
import { normalizeError } from '../utils/normalize-error';

interface CachedToken {
  accessToken: string;
  expiresAt: number;
}

@Injectable()
export class GraphAuthenticationProvider implements AuthenticationProvider {
  private readonly logger = new Logger(this.constructor.name);
  private readonly msalClient: ConfidentialClientApplication;
  private readonly scopes = ['https://graph.microsoft.com/.default'];
  private cachedToken: CachedToken | null = null;

  public constructor(private readonly configService: ConfigService) {
    const tenantId = this.configService.get<string>('sharepoint.tenantId') as string;
    const clientId = this.configService.get<string>('sharepoint.clientId') as string;
    const clientSecret = this.configService.get<string>('sharepoint.clientSecret') as string;

    if (!tenantId || !clientId || !clientSecret) {
      throw new Error(
        'SharePoint configuration missing: tenantId, clientId, and clientSecret are required',
      );
    }

    const msalConfig: Configuration = {
      auth: {
        clientId,
        authority: `https://login.microsoftonline.com/${tenantId}`,
        clientSecret,
      },
    };

    this.msalClient = new ConfidentialClientApplication(msalConfig);
  }

  public async getAccessToken(): Promise<string> {
    if (this.cachedToken && this.isTokenValid(this.cachedToken)) {
      return this.cachedToken.accessToken;
    }

    this.logger.debug('Acquiring new Microsoft Graph API token...');
    return await this.acquireNewToken();
  }

  private isTokenValid(token: CachedToken): boolean {
    const now = Date.now();
    return token.expiresAt > now;
  }

  private async acquireNewToken(): Promise<string> {
    const tokenRequest: ClientCredentialRequest = {
      scopes: this.scopes,
    };

    try {
      const response: AuthenticationResult | null =
        await this.msalClient.acquireTokenByClientCredential(tokenRequest);

      if (!response?.accessToken) {
        throw new Error('Failed to acquire Graph API token: no access token in response');
      }

      if (!response.expiresOn) {
        throw new Error('Failed to acquire Graph API token: no expiration time in response');
      }

      this.cachedToken = {
        accessToken: response.accessToken,
        expiresAt: response.expiresOn.getTime(),
      };

      this.logger.debug({
        msg: 'Successfully acquired new Microsoft Graph API token',
        expiresAt: response.expiresOn.toISOString(),
        cacheHit: false,
      });

      return response.accessToken;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to acquire Graph API token',
        error: serializeError(normalizeError(error)),
      });

      this.cachedToken = null;
      throw error;
    }
  }

  public clearTokenCache(): void {
    this.logger.debug('Clearing cached Microsoft Graph API token');
    this.cachedToken = null;
  }
}
