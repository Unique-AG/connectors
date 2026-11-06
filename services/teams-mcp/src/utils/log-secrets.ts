import { runWithLogSecrets } from '@unique-ag/logger';
import type {
  AMQPConfig,
  AuthConfig,
  DatabaseConfig,
  EncryptionConfig,
  MicrosoftConfig,
  UniqueConfig,
} from '~/config';

/** The secrets this deployment is configured with, redacted from every log line. */
export function deploymentSecrets({
  amqp,
  auth,
  database,
  encryption,
  microsoft,
  unique,
}: {
  amqp: AMQPConfig;
  auth: AuthConfig;
  database: DatabaseConfig;
  encryption: EncryptionConfig;
  microsoft: MicrosoftConfig;
  unique: UniqueConfig;
}): string[] {
  return [
    auth.hmacSecret.value,
    microsoft.clientSecret.value,
    microsoft.webhookSecret.value,
    // The key is configured, and so most likely leaked, in one of these encodings.
    encryption.key.value.toString('hex'),
    encryption.key.value.toString('hex').toUpperCase(),
    encryption.key.value.toString('base64'),
    ...urlPassword(database.url.value),
    ...urlPassword(amqp.url.value),
    ...uniqueAppKey(unique),
  ];
}

/** Scope for an AMQP handler outside a request. Place it below `@RabbitSubscribe`. */
export function LogSecretsScope() {
  return (
    _target: object,
    _key: string | symbol,
    descriptor: PropertyDescriptor,
  ): PropertyDescriptor => {
    const original = descriptor.value as (...args: unknown[]) => unknown;
    return {
      ...descriptor,
      value: function (this: unknown, ...args: unknown[]) {
        return runWithLogSecrets([], () => original.apply(this, args));
      },
    };
  };
}

// URL keeps the password encoded. The logger also matches each secret's encoded forms.
function urlPassword(url: URL): string[] {
  try {
    return [decodeURIComponent(url.password)];
  } catch {
    return [url.password];
  }
}

// In external mode the Unique app key is sent as `authorization: Bearer <app-key>`.
function uniqueAppKey(unique: UniqueConfig): string[] {
  if (unique.integration !== 'enabled' || unique.serviceAuthMode !== 'external') {
    return [];
  }
  const authorization = unique.serviceExtraHeaders.authorization ?? '';
  return [authorization.replace(/^bearer\s+/i, '')];
}
