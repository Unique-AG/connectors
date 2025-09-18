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
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { serializeError } from 'serialize-error-cjs';
import { normalizeError } from '../utils/normalize-error';

interface CachedToken {
  accessToken: string;
  expiresAt: number;
}

@Injectable()
export class GraphAuthenticationProvider implements AuthenticationProvider, OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);
  private readonly msalClient: ConfidentialClientApplication;
  // For delegated permissions, use the following scopes:
  // private readonly scopes = ['https://graph.microsoft.com/Sites.Read.All', 'https://graph.microsoft.com/Files.Read.All'];

  // For application permissions, use the following scopes:
  private readonly scopes = ['https://graph.microsoft.com/.default'];
  private cachedToken: CachedToken | null = null;

  public constructor(private readonly configService: ConfigService) {
    const tenantId = this.configService.get<string>('sharepoint.tenantId') ?? '';
    const clientId = this.configService.get<string>('sharepoint.clientId', '');
    const clientSecret = this.configService.get<string>('sharepoint.clientSecret', '');

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

  public async onModuleInit(): Promise<void> {
    // Eagerly acquire token on startup to catch configuration issues early
    try {
      // await this.getAccessToken();
      this.logger.log('Microsoft Graph authentication initialized successfully');
    } catch (error) {
      this.logger.error({
        msg: 'Failed to initialize Microsoft Graph authentication',
        error: serializeError(normalizeError(error)),
      });
      throw error;
    }
  }

  /**
   * Implementation of AuthenticationProvider interface for Microsoft Graph SDK
   */
  public async getAccessToken(
    _authenticationProviderOptions?: AuthenticationProviderOptions,
  ): Promise<string> {
    // Check if we have a valid cached token
    if (this.cachedToken && this.isTokenValid(this.cachedToken)) {
      return this.cachedToken.accessToken;
    }

    this.logger.log('Acquiring new Microsoft Graph API token...');
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

  /**
   * Clears the cached token, forcing the next getAccessToken() call to acquire a fresh token
   */
  public clearTokenCache(): void {
    this.logger.debug('Clearing cached Microsoft Graph API token');
    this.cachedToken = null;
  }
}
