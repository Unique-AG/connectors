import { IncomingMessage } from 'node:http';
import { Socket } from 'node:net';
import { describe, expect, it } from 'vitest';
import type {
  AMQPConfig,
  AuthConfig,
  DatabaseConfig,
  EncryptionConfig,
  MicrosoftConfig,
  UniqueConfig,
} from '~/config';
import { Redacted } from '~/utils/redacted';
import { bearerToken, deploymentSecrets } from '../log-secrets';

const mockEncryptionKey = Buffer.alloc(32, 7);

const mockConfigs = {
  amqp: { url: new Redacted(new URL('amqp://app:amqp-password-1@rabbit:5672')) } as AMQPConfig,
  auth: { hmacSecret: new Redacted('hmac-secret-value') } as AuthConfig,
  database: {
    url: new Redacted(new URL('postgresql://app:db%2Fpassword-1@db:5432/outlook')),
  } as DatabaseConfig,
  encryption: { key: new Redacted(mockEncryptionKey) } as EncryptionConfig,
  microsoft: {
    clientSecret: new Redacted('microsoft-client-secret'),
    webhookSecret: new Redacted('w'.repeat(128)),
  } as MicrosoftConfig,
  unique: { serviceAuthMode: 'cluster_local' } as UniqueConfig,
};

function requestWith(authorization: string | undefined): IncomingMessage {
  const request = new IncomingMessage(new Socket());
  if (authorization !== undefined) {
    request.headers.authorization = authorization;
  }
  return request;
}

describe('deploymentSecrets', () => {
  it('lists the configured secrets, the encryption key in both its encodings', () => {
    expect(deploymentSecrets(mockConfigs)).toEqual([
      'hmac-secret-value',
      'microsoft-client-secret',
      'w'.repeat(128),
      mockEncryptionKey.toString('hex'),
      mockEncryptionKey.toString('base64'),
      'db%2Fpassword-1',
      'db/password-1',
      'amqp-password-1',
      'amqp-password-1',
    ]);
  });

  it('adds the Zitadel client secret in external mode', () => {
    const unique = {
      serviceAuthMode: 'external',
      zitadelClientSecret: 'zitadel-client-secret',
    } as UniqueConfig;

    expect(deploymentSecrets({ ...mockConfigs, unique })).toContain('zitadel-client-secret');
  });
});

describe('bearerToken', () => {
  it('returns the token of a bearer authorization header', () => {
    expect(bearerToken(requestWith('Bearer mcp-access-token'))).toEqual(['mcp-access-token']);
  });

  it.each([
    ['no authorization header', undefined],
    ['another scheme', 'Basic dXNlcjpwYXNz'],
    ['a scheme without a token', 'Bearer'],
  ])('returns nothing for %s', (_case, authorization) => {
    expect(bearerToken(requestWith(authorization))).toEqual([]);
  });
});
