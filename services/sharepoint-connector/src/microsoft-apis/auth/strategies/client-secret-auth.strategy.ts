import assert from 'node:assert';
import { ConfidentialClientApplication, type Configuration } from '@azure/msal-node';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { serializeError } from 'serialize-error-cjs';
import { Config } from '../../../config';
import { normalizeError } from '../../../utils/normalize-error';
import { TokenAcquisitionResult } from '../types';
import { AuthStrategy } from './auth-strategy.interface';

@Injectable()
export class ClientSecretAuthStrategy implements AuthStrategy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly msalClient: ConfidentialClientApplication;

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const sharePointConfig = this.configService.get('sharepoint', { infer: true });

    assert.strictEqual(
      sharePointConfig.authMode,
      'client-secret',
      'ClientSecretAuthStrategy called but authentication mode is not "client-secret"',
    );

    const {
      authTenantId: tenantId,
      authClientId: clientId,
      authClientSecret: clientSecret,
    } = sharePointConfig;

    const msalConfig: Configuration = {
      auth: {
        clientId,
        authority: `https://login.microsoftonline.com/${tenantId}`,
        clientSecret: clientSecret.value,
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
        error: serializeError(normalizeError(error)),
      });

      throw error;
    }
  }
}
