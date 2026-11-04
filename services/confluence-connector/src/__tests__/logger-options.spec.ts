import assert from 'node:assert';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import pino from 'pino';
import { afterAll, describe, expect, it } from 'vitest';
import type {
  AppConfig,
  ConfluenceConfig,
  NamedTenantConfig,
  ProxyConfig,
  TenantConfig,
  UniqueConfig,
} from '../config';
import { createAppLoggerOptions, deploymentSecrets } from '../logger-options';
import { Redacted } from '../utils/redacted';

const mockAppConfig = { logLevel: 'info' } as AppConfig;

const mockNoProxyConfig: ProxyConfig = { authMode: 'none' };

const mockBasicProxyConfig: ProxyConfig = {
  authMode: 'username_password',
  host: 'proxy.example.com',
  port: 3128,
  protocol: 'http',
  username: 'proxy-user',
  password: new Redacted('proxy-password-1'),
};

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

function mockTenant(
  name: string,
  auth: ConfluenceConfig['auth'],
  unique: UniqueConfig,
): NamedTenantConfig {
  return {
    name,
    status: 'active',
    config: { confluence: { auth }, unique } as TenantConfig,
  };
}

const mockTenants = [
  mockTenant(
    'cloud-tenant',
    {
      mode: 'oauth_2lo',
      clientId: 'confluence-client-id',
      clientSecret: new Redacted('confluence-client-secret'),
    },
    mockExternalUniqueConfig,
  ),
  mockTenant(
    'pat-tenant',
    { mode: 'pat', token: new Redacted('confluence-personal-token') },
    mockClusterLocalUniqueConfig,
  ),
  mockTenant(
    'basic-tenant',
    {
      mode: 'basic',
      username: new Redacted('confluence-user'),
      password: new Redacted('confluence-password-1'),
    },
    mockClusterLocalUniqueConfig,
  ),
];

const mockPrivateKey =
  '-----BEGIN PRIVATE KEY-----\nZmFrZS1wcm94eS1rZXk=\n-----END PRIVATE KEY-----';
const keyDirectory = mkdtempSync(join(tmpdir(), 'confluence-connector-logger-options-'));
const keyPath = join(keyDirectory, 'proxy-client.key');
writeFileSync(keyPath, `${mockPrivateKey}\n`);

const mockTlsProxyConfig: ProxyConfig = {
  authMode: 'ssl_tls',
  host: 'proxy.example.com',
  port: 3128,
  protocol: 'https',
  sslCertPath: join(keyDirectory, 'proxy-client.crt'),
  sslKeyPath: keyPath,
};

afterAll(() => rmSync(keyDirectory, { recursive: true, force: true }));

describe('deploymentSecrets', () => {
  it("lists each tenant's Confluence and Zitadel secrets, a Basic pair also encoded", () => {
    expect(deploymentSecrets(mockNoProxyConfig, mockTenants)).toEqual([
      'confluence-client-secret',
      'zitadel-client-secret',
      'confluence-personal-token',
      'confluence-password-1',
      Buffer.from('confluence-user:confluence-password-1').toString('base64'),
    ]);
  });

  it('adds the proxy password and its encoded Basic pair', () => {
    expect(deploymentSecrets(mockBasicProxyConfig, [])).toEqual([
      'proxy-password-1',
      Buffer.from('proxy-user:proxy-password-1').toString('base64'),
    ]);
  });

  it('adds the whole proxy TLS client key', () => {
    expect(deploymentSecrets(mockTlsProxyConfig, [])).toEqual([mockPrivateKey]);
  });
});

describe('createAppLoggerOptions', () => {
  function createCapturingLogger(proxy: ProxyConfig) {
    const pinoHttpOptions = createAppLoggerOptions(mockAppConfig, proxy, mockTenants).pinoHttp;
    assert.ok(
      typeof pinoHttpOptions === 'object' && pinoHttpOptions !== null && 'hooks' in pinoHttpOptions,
      'Expected pinoHttp options with hooks',
    );
    const lines: string[] = [];
    const logger = pino({ hooks: pinoHttpOptions.hooks }, { write: (line) => lines.push(line) });
    return { logger, lines };
  }

  it('redacts the proxy and tenant secrets from every line', () => {
    const { logger, lines } = createCapturingLogger(mockBasicProxyConfig);

    logger.error('rejected confluence-client-secret and zitadel-client-secret');
    logger.error('rejected proxy-password-1');

    expect(lines.map((line) => JSON.parse(line).msg)).toEqual([
      'rejected [Redacted] and [Redacted]',
      'rejected [Redacted]',
    ]);
  });

  it('redacts the proxy TLS client key from every line', () => {
    const { logger, lines } = createCapturingLogger(mockTlsProxyConfig);

    logger.error(`key ${mockPrivateKey}`);

    expect(JSON.parse(lines[0] ?? '{}').msg).toBe('key [Redacted]');
  });
});
