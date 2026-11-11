import { readFileSync } from 'node:fs';
import { createLoggerOptions } from '@unique-ag/logger';
import { context, trace } from '@opentelemetry/api';
import type { Params } from 'nestjs-pino';
import {
  type AppConfig,
  AuthMode,
  type ConfluenceConfig,
  type NamedTenantConfig,
  type ProxyConfig,
  UniqueAuthMode,
  type UniqueConfig,
} from './config';
import { tenantStorage } from './tenant/tenant-context.storage';
import { Redacted } from './utils/redacted';

export function createAppLoggerOptions(
  app: AppConfig,
  proxy: ProxyConfig,
  tenants: readonly NamedTenantConfig[],
): Params {
  const loggerOptions = createLoggerOptions({ secrets: deploymentSecrets(proxy, tenants) });
  return {
    ...loggerOptions,
    pinoHttp: {
      ...loggerOptions.pinoHttp,
      level: app.logLevel,
      // Injects tenantName into every log. Logs emitted before tenantStorage.run() is
      // called (during bootstrap) won't have it — those sites must set it explicitly.
      mixin: () => {
        const tenant = tenantStorage.getStore();
        return tenant ? { tenantName: tenant.name } : {};
      },
      genReqId: () => {
        const ctx = trace.getSpanContext(context.active());
        if (!ctx) {
          return crypto.randomUUID();
        }
        return ctx.traceId;
      },
      redact: {
        paths: ['req.headers.authorization'],
        censor: (value) => (value instanceof Redacted ? value : new Redacted(value)),
      },
    },
  };
}

/** The secrets this deployment and its tenants are configured with, redacted from every log line. */
export function deploymentSecrets(
  proxy: ProxyConfig,
  tenants: readonly NamedTenantConfig[],
): string[] {
  return [
    ...proxySecrets(proxy),
    ...tenants.flatMap(({ config }) => [
      ...confluenceSecrets(config.confluence.auth),
      ...uniqueSecrets(config.unique),
    ]),
  ];
}

function proxySecrets(proxy: ProxyConfig): string[] {
  switch (proxy.authMode) {
    case 'username_password':
      return [proxy.password.value, basicCredentials(proxy.username, proxy.password.value)];
    case 'ssl_tls':
      return [readFileSync(proxy.sslKeyPath, 'utf-8').trim()];
    default:
      return [];
  }
}

function confluenceSecrets(auth: ConfluenceConfig['auth']): string[] {
  switch (auth.mode) {
    case AuthMode.OAuth2Lo:
      return [auth.clientSecret.value];
    case AuthMode.Pat:
      return [auth.token.value];
    case AuthMode.Basic:
      return [auth.password.value, basicCredentials(auth.username.value, auth.password.value)];
  }
}

function uniqueSecrets(unique: UniqueConfig): string[] {
  return unique.serviceAuthMode === UniqueAuthMode.External
    ? [
        unique.zitadelClientSecret.value,
        basicCredentials(unique.zitadelClientId, unique.zitadelClientSecret.value),
      ]
    : [];
}

// What an HTTP Basic `Authorization` header carries, so the encoded pair is redacted too.
function basicCredentials(username: string, password: string): string {
  return Buffer.from(`${username}:${password}`, 'utf8').toString('base64');
}
