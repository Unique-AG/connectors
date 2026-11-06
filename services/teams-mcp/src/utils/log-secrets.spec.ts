import assert from 'node:assert';
import { addLogSecrets, createLoggerOptions } from '@unique-ag/logger';
import { RABBIT_HANDLER, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import pino from 'pino';
import { describe, expect, it } from 'vitest';
import type {
  AMQPConfig,
  AuthConfig,
  DatabaseConfig,
  EncryptionConfig,
  MicrosoftConfig,
  UniqueConfig,
} from '~/config';
import { deploymentSecrets, LogSecretsScope } from './log-secrets';
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

describe('LogSecretsScope', () => {
  const mockToken = 'graph-refresh-token-1234';

  function createCapturingLogger() {
    const pinoHttpOptions = createLoggerOptions().pinoHttp;
    assert.ok(
      typeof pinoHttpOptions === 'object' && pinoHttpOptions !== null && 'hooks' in pinoHttpOptions,
      'Expected pinoHttp options with hooks',
    );
    const lines: string[] = [];
    const logger = pino({ hooks: pinoHttpOptions.hooks }, { write: (line) => lines.push(line) });
    return { logger, lines };
  }

  it('redacts a token the handler adds from what it logs, and only while it runs', async () => {
    const { logger, lines } = createCapturingLogger();
    class SyncListener {
      @LogSecretsScope()
      public async onSync(): Promise<string> {
        addLogSecrets([mockToken]);
        logger.error(`Graph rejected ${mockToken}`);
        return 'done';
      }
    }

    await expect(new SyncListener().onSync()).resolves.toBe('done');
    logger.error(`after ${mockToken}`);

    expect(lines.map((line) => JSON.parse(line).msg)).toEqual([
      'Graph rejected [Redacted]',
      `after ${mockToken}`,
    ]);
  });

  it('keeps the RabbitSubscribe metadata of the handler it wraps', () => {
    class SyncListener {
      @RabbitSubscribe({ exchange: 'main', routingKey: 'sync', queue: 'sync' })
      @LogSecretsScope()
      public async onSync(): Promise<void> {}
    }

    expect(Reflect.getMetadata(RABBIT_HANDLER, SyncListener.prototype.onSync)).toMatchObject({
      queue: 'sync',
    });
  });
});
