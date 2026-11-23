import assert from 'node:assert';
import crypto from 'node:crypto';
import { readFileSync } from 'node:fs';
import { ConfidentialClientApplication, type Configuration } from '@azure/msal-node';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Dispatcher } from 'undici';
import { Config } from '../../../config';
import { sanitizeError } from '../../../utils/normalize-error';
import type { Redacted } from '../../../utils/redacted';
import { ProxiedMsalNetworkClient } from '../msal-proxy-config';
import { TokenAcquisitionResult } from '../types';
import { AuthStrategy } from './auth-strategy.interface';

@Injectable()
export class CertificateAuthStrategy implements AuthStrategy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly msalClient: ConfidentialClientApplication;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly dispatcher: Dispatcher,
  ) {
    const sharePointConfig = this.configService.get('sharepoint', { infer: true });

    assert.strictEqual(
      sharePointConfig.auth.mode,
      'certificate',
      'CertificateAuthStrategy called but authentication mode is not "certificate"',
    );

    const { tenantId } = sharePointConfig;
    const {
      clientId,
      privateKeyPath,
      thumbprintSha1: thumbprint,
      thumbprintSha256,
      privateKeyPassword,
    } = sharePointConfig.auth;

    const { unencrypted: privateKey } = readCertificatePrivateKey(
      privateKeyPath,
      privateKeyPassword,
    );

    const msalConfig: Configuration = {
      auth: {
        clientId,
        authority: `https://login.microsoftonline.com/${tenantId}`,
        clientCertificate: {
          privateKey,
          ...(thumbprintSha256 ? { thumbprintSha256 } : { thumbprint }),
        },
      },
      system: {
        networkClient: new ProxiedMsalNetworkClient(this.dispatcher),
      },
    };

    this.msalClient = new ConfidentialClientApplication(msalConfig);
  }

  public async acquireNewToken(scopes: string[]): Promise<TokenAcquisitionResult> {
    this.logger.log('Acquiring new Graph API token using client certificate');

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
        msg: 'Failed to acquire Graph API token using client certificate',
        error: sanitizeError(error),
      });

      throw error;
    }
  }
}

/** The key as its file stores it, and the unencrypted PKCS#8 PEM MSAL signs with. */
export function readCertificatePrivateKey(
  privateKeyPath: string,
  privateKeyPassword: Redacted<string> | undefined,
): { stored: string; unencrypted: string } {
  const stored = readFileSync(privateKeyPath, 'utf8').trim();
  if (!privateKeyPassword) {
    return { stored, unencrypted: stored };
  }

  const unencrypted = crypto
    .createPrivateKey({ key: stored, passphrase: privateKeyPassword.value, format: 'pem' })
    .export({ format: 'pem', type: 'pkcs8' })
    .toString();
  return { stored, unencrypted };
}
