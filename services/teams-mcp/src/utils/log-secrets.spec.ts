import { describe, expect, it } from 'vitest';
import type {
  AMQPConfig,
  AuthConfig,
  DatabaseConfig,
  EncryptionConfig,
  MicrosoftConfig,
  UniqueConfig,
} from '~/config';
import { deploymentSecrets } from './log-secrets';
import { Redacted } from './redacted';

const mockEncryptionKey = Buffer.alloc(32, 7);

const mockConfigs = {
  amqp: { url: new Redacted(new URL('amqp://app:amqp-password-1@rabbit:5672')) } as AMQPConfig,
  auth: { hmacSecret: new Redacted('hmac-secret-value') } as AuthConfig,
  database: {
    url: new Redacted(new URL('postgresql://app:db%2Fpassword-1@db:5432/teams')),
  } as DatabaseConfig,
  encryption: { key: new Redacted(mockEncryptionKey) } as EncryptionConfig,
  microsoft: {
    clientSecret: new Redacted('microsoft-client-secret'),
    webhookSecret: new Redacted('w'.repeat(128)),
  } as MicrosoftConfig,
  unique: { integration: 'disabled' } as UniqueConfig,
};

describe('deploymentSecrets', () => {
  it('lists the configured secrets, the encryption key in each of its encodings', () => {
    expect(deploymentSecrets(mockConfigs)).toEqual([
      'hmac-secret-value',
      'microsoft-client-secret',
      'w'.repeat(128),
      mockEncryptionKey.toString('hex'),
      mockEncryptionKey.toString('hex').toUpperCase(),
      mockEncryptionKey.toString('base64'),
      'db/password-1',
      'amqp-password-1',
    ]);
  });

  it('adds the Unique app key in external mode', () => {
    const unique = {
      integration: 'enabled',
      serviceAuthMode: 'external',
      serviceExtraHeaders: { authorization: 'Bearer unique-app-key-1' },
    } as unknown as UniqueConfig;

    expect(deploymentSecrets({ ...mockConfigs, unique })).toContain('unique-app-key-1');
  });

  it('adds nothing for Unique in cluster-local mode', () => {
    const unique = {
      integration: 'enabled',
      serviceAuthMode: 'cluster_local',
      serviceExtraHeaders: { 'x-company-id': 'company-1', 'x-user-id': 'service-user-1' },
    } as unknown as UniqueConfig;

    expect(deploymentSecrets({ ...mockConfigs, unique })).toEqual(deploymentSecrets(mockConfigs));
  });
});
