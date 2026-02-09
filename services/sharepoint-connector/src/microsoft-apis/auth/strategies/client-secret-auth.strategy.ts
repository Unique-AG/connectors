import assert from 'node:assert';
import { ConfidentialClientApplication, type Configuration } from '@azure/msal-node';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Dispatcher } from 'undici';
import { Config } from '../../../config';
import { sanitizeError } from '../../../utils/normalize-error';
import { ProxiedMsalNetworkClient } from '../msal-proxy-config';
import { TokenAcquisitionResult } from '../types';
import { AuthStrategy } from './auth-strategy.interface';

@Injectable()
export class ClientSecretAuthStrategy implements AuthStrategy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly msalClient: ConfidentialClientApplication;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly dispatcher: Dispatcher,
  ) {
    const sharePointConfig = this.configService.get('sharepoint', { infer: true });

    assert.strictEqual(
      sharePointConfig.auth.mode,
      'client-secret',
      'ClientSecretAuthStrategy called but authentication mode is not "client-secret"',
    );

    const { tenantId } = sharePointConfig;
    const { clientId, clientSecret } = sharePointConfig.auth;

    const msalConfig: Configuration = {
      auth: {
        clientId,
        authority: `https://login.microsoftonline.com/${tenantId}`,
        clientSecret: clientSecret.value,
      },
      system: {
        networkClient: new ProxiedMsalNetworkClient(this.dispatcher),
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
