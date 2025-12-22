import assert from 'node:assert';
import { ConfidentialClientApplication, type Configuration } from '@azure/msal-node';
import { Injectable, Logger } from '@nestjs/common';
import { TenantConfig } from '../../../config/tenant-config.schema';
import { sanitizeError } from '../../../utils/normalize-error';
import { TokenAcquisitionResult } from '../types';
import { AuthStrategy } from './auth-strategy.interface';

@Injectable()
export class ClientSecretAuthStrategy implements AuthStrategy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly msalClient: ConfidentialClientApplication;

  public constructor(tenantConfig: TenantConfig) {
    assert.strictEqual(
      tenantConfig.authStrategy,
      'client-secret',
      `ClientSecretAuthStrategy called but authentication mode is not "client-secret" (was: ${tenantConfig.authStrategy})`,
    );

    const tenantId = tenantConfig.tenantId;
    const clientId = tenantConfig.clientId;
    const clientSecretValue = tenantConfig.clientSecret;

    assert.ok(clientId, 'Client ID must be provided for client-secret authentication');
    assert.ok(clientSecretValue, 'Client secret must be provided for client-secret authentication');

    const msalConfig: Configuration = {
      auth: {
        clientId,
        authority: `https://login.microsoftonline.com/${tenantId}`,
        clientSecret: clientSecretValue,
      },
    };

    this.msalClient = new ConfidentialClientApplication(msalConfig);
  }

  public async acquireNewToken(scopes: string[]): Promise<TokenAcquisitionResult> {
    this.logger.log('Acquiring new Graph API token using client secret');

    try {
      const response = await this.msalClient.acquireTokenByClientCredential({ scopes });

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
        msg: 'Failed to acquire Graph API token using client secret',
        error: sanitizeError(error),
      });

      throw error;
    }
  }
}
