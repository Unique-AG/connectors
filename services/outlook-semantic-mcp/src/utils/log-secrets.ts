import type { IncomingMessage } from 'node:http';
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
    encryption.key.value.toString('base64'),
    ...urlPassword(database.url.value),
    ...urlPassword(amqp.url.value),
    ...(unique.serviceAuthMode === 'external' ? [unique.zitadelClientSecret] : []),
  ];
}

/** The MCP access token a request carries, redacted from every line logged while it is handled. */
export function bearerToken(request: IncomingMessage): string[] {
  const [scheme, token] = (request.headers.authorization ?? '').split(' ');
  return scheme?.toLowerCase() === 'bearer' && token ? [token] : [];
}

// The password as it is and as the URL encodes it.
function urlPassword(url: URL): string[] {
  try {
    return [url.password, decodeURIComponent(url.password)];
  } catch {
    return [url.password];
  }
}
