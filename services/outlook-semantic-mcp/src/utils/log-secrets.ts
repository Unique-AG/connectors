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
    ...(unique.serviceAuthMode === 'external' ? [unique.zitadelClientSecret] : []),
  ];
}

/**
 * Opens a log-secret scope for each run of an AMQP handler or scheduled job, which runs outside any
 * HTTP request, so a token it reads with `addLogSecrets` is redacted from what it logs. Put it
 * directly above `@NewTrace`, below `@RabbitSubscribe`, so that one attaches its metadata to the
 * function this returns.
 */
export function LogSecretsScope(): MethodDecorator {
  return (_target, _key, descriptor: PropertyDescriptor) => {
    const original = descriptor.value as (...args: unknown[]) => unknown;
    descriptor.value = function (...args: unknown[]) {
      return runWithLogSecrets([], () => original.apply(this, args));
    };
    return descriptor;
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
