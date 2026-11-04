import assert from 'node:assert';
import { generateKeyPairSync } from 'node:crypto';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import pino from 'pino';
import { afterAll, describe, expect, it } from 'vitest';
import type { ProxyConfig } from './config/proxy.config';
import type { AppConfig, SharepointConfig, UniqueConfig } from './config/tenant-config-loader';
import { createAppLoggerOptions, deploymentSecrets } from './logger-options';
import { Redacted } from './utils/redacted';

const mockAppConfig = { logLevel: 'info' } as AppConfig;

const mockClientSecretSharepointConfig = {
  auth: {
    mode: 'client-secret',
    clientId: 'microsoft-client-id',
    clientSecret: new Redacted('microsoft-client-secret'),
  },
} as SharepointConfig;

const mockUniqueServiceUrls = {
  ingestionServiceBaseUrl: 'http://ingestion:8091',
  scopeManagementServiceBaseUrl: 'http://scope:8094',
  apiRateLimitPerMinute: 100,
};

const mockClusterLocalUniqueConfig: UniqueConfig = {
  ...mockUniqueServiceUrls,
  serviceAuthMode: 'cluster_local',
  serviceExtraHeaders: { 'x-company-id': 'company-1', 'x-user-id': 'user-1' },
};

const mockExternalUniqueConfig: UniqueConfig = {
  ...mockUniqueServiceUrls,
  serviceAuthMode: 'external',
  zitadelOauthTokenUrl: 'https://zitadel.example.com/oauth/v2/token',
  zitadelProjectId: new Redacted('zitadel-project-1'),
  zitadelClientId: 'zitadel-client-id',
  zitadelClientSecret: new Redacted('zitadel-client-secret'),
};

const mockNoProxyConfig: ProxyConfig = { authMode: 'none' };

const mockBasicProxyConfig: ProxyConfig = {
  authMode: 'username_password',
  host: 'proxy.example.com',
  port: 3128,
  protocol: 'http',
  username: 'proxy-user',
  password: new Redacted('proxy-password-1'),
};

const mockKeyPassword = 'private-key-password';
const { privateKey } = generateKeyPairSync('ed25519');
const mockPrivateKey = privateKey.export({ type: 'pkcs8', format: 'pem' }).toString();
const mockEncryptedPrivateKey = privateKey
  .export({ type: 'pkcs8', format: 'pem', cipher: 'aes-256-cbc', passphrase: mockKeyPassword })
  .toString();

const keyDirectory = mkdtempSync(join(tmpdir(), 'sharepoint-connector-logger-options-'));
const keyPath = join(keyDirectory, 'certificate.key');
const encryptedKeyPath = join(keyDirectory, 'certificate-encrypted.key');
const proxyKeyPath = join(keyDirectory, 'proxy-client.key');
writeFileSync(keyPath, mockPrivateKey);
writeFileSync(encryptedKeyPath, mockEncryptedPrivateKey);
writeFileSync(proxyKeyPath, mockPrivateKey);

const mockCertificateSharepointConfig = {
  auth: {
    mode: 'certificate',
    clientId: 'microsoft-client-id',
    thumbprintSha256: 'ab12',
    privateKeyPath: keyPath,
  },
} as SharepointConfig;

const mockEncryptedCertificateSharepointConfig = {
  auth: {
    mode: 'certificate',
    clientId: 'microsoft-client-id',
    thumbprintSha256: 'ab12',
    privateKeyPath: encryptedKeyPath,
    privateKeyPassword: new Redacted(mockKeyPassword),
  },
} as SharepointConfig;

const mockTlsProxyConfig: ProxyConfig = {
  authMode: 'ssl_tls',
  host: 'proxy.example.com',
  port: 3128,
  protocol: 'https',
  sslCertPath: join(keyDirectory, 'proxy-client.crt'),
  sslKeyPath: proxyKeyPath,
};

afterAll(() => rmSync(keyDirectory, { recursive: true, force: true }));

describe('deploymentSecrets', () => {
  it('lists the Microsoft client secret', () => {
    expect(
      deploymentSecrets({
        sharepoint: mockClientSecretSharepointConfig,
        unique: mockClusterLocalUniqueConfig,
        proxy: mockNoProxyConfig,
      }),
    ).toEqual(['microsoft-client-secret']);
  });

  it('adds the Zitadel client secret in external mode', () => {
    expect(
      deploymentSecrets({
        sharepoint: mockClientSecretSharepointConfig,
        unique: mockExternalUniqueConfig,
        proxy: mockNoProxyConfig,
      }),
    ).toEqual(['microsoft-client-secret', 'zitadel-client-secret']);
  });

  it('lists the whole certificate private key', () => {
    expect(
      deploymentSecrets({
        sharepoint: mockCertificateSharepointConfig,
        unique: mockClusterLocalUniqueConfig,
        proxy: mockNoProxyConfig,
      }),
    ).toEqual([mockPrivateKey.trim()]);
  });

  it('lists an encrypted private key as stored and unencrypted, and its password', () => {
    expect(
      deploymentSecrets({
        sharepoint: mockEncryptedCertificateSharepointConfig,
        unique: mockClusterLocalUniqueConfig,
        proxy: mockNoProxyConfig,
      }),
    ).toEqual([mockEncryptedPrivateKey.trim(), mockPrivateKey, mockKeyPassword]);
  });

  it('adds the proxy password and its encoded Basic pair', () => {
    expect(
      deploymentSecrets({
        sharepoint: mockClientSecretSharepointConfig,
        unique: mockClusterLocalUniqueConfig,
        proxy: mockBasicProxyConfig,
      }),
    ).toEqual([
      'microsoft-client-secret',
      'proxy-password-1',
      Buffer.from('proxy-user:proxy-password-1').toString('base64'),
    ]);
  });

  it('adds the whole proxy TLS client key', () => {
    expect(
      deploymentSecrets({
        sharepoint: mockClientSecretSharepointConfig,
        unique: mockClusterLocalUniqueConfig,
        proxy: mockTlsProxyConfig,
      }),
    ).toEqual(['microsoft-client-secret', mockPrivateKey.trim()]);
  });
});

describe('createAppLoggerOptions', () => {
  function createCapturingLogger(sharepoint: SharepointConfig) {
    const pinoHttpOptions = createAppLoggerOptions(mockAppConfig, {
      sharepoint,
      unique: mockExternalUniqueConfig,
      proxy: mockBasicProxyConfig,
    }).pinoHttp;
    assert.ok(
      typeof pinoHttpOptions === 'object' && pinoHttpOptions !== null && 'hooks' in pinoHttpOptions,
      'Expected pinoHttp options with hooks',
    );
    const lines: string[] = [];
    const logger = pino({ hooks: pinoHttpOptions.hooks }, { write: (line) => lines.push(line) });
    return { logger, lines };
  }

  it('redacts the configured secrets from every line', () => {
    const { logger, lines } = createCapturingLogger(mockClientSecretSharepointConfig);

    logger.error('rejected microsoft-client-secret and zitadel-client-secret');
    logger.error('rejected proxy-password-1');

    expect(lines.map((line) => JSON.parse(line).msg)).toEqual([
      'rejected [Redacted] and [Redacted]',
      'rejected [Redacted]',
    ]);
  });

  it('redacts the unencrypted certificate private key from every line', () => {
    const { logger, lines } = createCapturingLogger(mockEncryptedCertificateSharepointConfig);

    logger.error(`key ${mockPrivateKey}`);

    expect(JSON.parse(lines[0] ?? '{}').msg).toBe('key [Redacted]');
  });
});
