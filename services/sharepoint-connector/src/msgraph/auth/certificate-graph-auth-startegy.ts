import assert from 'node:assert';
import crypto from 'node:crypto';
import { readFileSync } from 'node:fs';
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
export class CertificateGraphAuthStrategy implements GraphAuthStrategy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly msalClient: ConfidentialClientApplication;
  private readonly scopes = ['https://graph.microsoft.com/.default'];
  private readonly tokenCache = new TokenCache();

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const sharePointConfig = this.configService.get('sharepoint', { infer: true });

    assert.strictEqual(
      sharePointConfig.authMode,
      'certificate',
      'CertificateGraphAuthStrategy called but authentication mode is not "certificate"',
    );

    const {
      authTenantId: tenantId,
      authClientId: clientId,
      authPrivateKeyPath: privateKeyPath,
      authThumbprintSha1: thumbprint,
      authThumbprintSha256: thumbprintSha256,
      authPrivateKeyPassword: privateKeyPassword,
    } = sharePointConfig;

    const privateKeyRaw = readFileSync(privateKeyPath, 'utf8').trim();

    let privateKey: string;
    if (privateKeyPassword) {
      const privateKeyObject = crypto.createPrivateKey({
        key: privateKeyRaw,
        passphrase: privateKeyPassword,
        format: 'pem',
      });
      privateKey = privateKeyObject.export({ format: 'pem', type: 'pkcs8' }).toString();
    } else {
      privateKey = privateKeyRaw;
    }

    const msalConfig: Configuration = {
      auth: {
        clientId,
        authority: `https://login.microsoftonline.com/${tenantId}`,
        clientCertificate: {
          privateKey,
          ...(thumbprintSha256 ? { thumbprintSha256 } : { thumbprint }),
        },
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

    this.logger.log('Acquiring new Graph API token using client certificate');

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
        msg: 'Failed to acquire Graph API token using client certificate',
        error: serializeError(normalizeError(error)),
      });

      throw error;
    }
  }
}
