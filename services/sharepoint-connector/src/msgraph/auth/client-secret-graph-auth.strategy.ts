import assert from 'node:assert';
import {
  type ClientCredentialRequest,
  ConfidentialClientApplication,
  type Configuration,
} from '@azure/msal-node';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { serializeError } from 'serialize-error-cjs';
import { Config } from '../../config';
import { normalizeError } from '../../utils/normalize-error';
import { GraphAuthStrategy } from './graph-auth-strategy.interface';
import { TokenAcquisitionResult, TokenCache } from './token-cache';

@Injectable()
export class ClientSecretGraphAuthStrategy implements GraphAuthStrategy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly msalClient: ConfidentialClientApplication;
  private readonly scopes = ['https://graph.microsoft.com/.default'];
  private readonly tokenCache = new TokenCache();

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const tenantId = this.configService.get('sharepoint.graphTenantId', { infer: true });
    const clientId = this.configService.get('sharepoint.graphClientId', { infer: true });
    const clientSecret = this.configService.get('sharepoint.graphClientSecret', { infer: true });

    assert.ok(
      tenantId && clientId && clientSecret,
      'SharePoint configuration missing: tenantId, clientId, and clientSecret are required when using client secret authentication',
    );

    const msalConfig: Configuration = {
      auth: {
        clientId,
        authority: `https://login.microsoftonline.com/${tenantId}`,
        clientSecret: clientSecret.value,
      },
    };

    this.msalClient = new ConfidentialClientApplication(msalConfig);
  }

  public async getAccessToken(): Promise<string> {
    return this.tokenCache.getToken(() => this.acquireNewToken());
  }

  private async acquireNewToken(): Promise<TokenAcquisitionResult> {
    const tokenRequest: ClientCredentialRequest = {
      scopes: this.scopes,
    };

    this.logger.log('Acquiring new Graph API token using client secret');

    try {
      const response = await this.msalClient.acquireTokenByClientCredential(tokenRequest);

      assert.ok(
        response?.accessToken,
        'Failed to acquire Graph API token: no access token in response',
      );
      assert.ok(
        response.expiresOn,
        'Failed to acquire Graph API token: no expiration time in response',
      );

      return {
        token: response.accessToken,
        expiresAt: response.expiresOn.getTime(),
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to acquire Graph API token',
        error: serializeError(normalizeError(error)),
      });

      throw error;
    }
  }
}
