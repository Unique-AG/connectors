import { readFileSync } from 'node:fs';
import { createLoggerOptions } from '@unique-ag/logger';
import { context, trace } from '@opentelemetry/api';
import type { Params } from 'nestjs-pino';
import type { ProxyConfig } from './config/proxy.config';
import type { AppConfig, SharepointConfig, UniqueConfig } from './config/tenant-config-loader';
import { readCertificatePrivateKey } from './microsoft-apis/auth/strategies/certificate-auth.strategy';
import { Redacted } from './utils/redacted';

interface DeploymentConfigs {
  sharepoint: SharepointConfig;
  unique: UniqueConfig;
  proxy: ProxyConfig;
}

export function createAppLoggerOptions(app: AppConfig, configs: DeploymentConfigs): Params {
  const loggerOptions = createLoggerOptions({ secrets: deploymentSecrets(configs) });
  return {
    ...loggerOptions,
    pinoHttp: {
      ...loggerOptions.pinoHttp,
      level: app.logLevel,
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

/** The secrets this deployment is configured with, redacted from every log line. */
export function deploymentSecrets({ sharepoint, unique, proxy }: DeploymentConfigs): string[] {
  return [
    ...microsoftSecrets(sharepoint.auth),
    ...(unique.serviceAuthMode === 'external'
      ? [
          unique.zitadelClientSecret.value,
          basicCredentials(unique.zitadelClientId, unique.zitadelClientSecret.value),
        ]
      : []),
    ...proxySecrets(proxy),
  ];
}

function microsoftSecrets(auth: SharepointConfig['auth']): string[] {
  switch (auth.mode) {
    case 'client-secret':
      return [auth.clientSecret.value];
    case 'certificate': {
      const { stored, unencrypted } = readCertificatePrivateKey(
        auth.privateKeyPath,
        auth.privateKeyPassword,
      );
      return [
        stored,
        ...(unencrypted === stored ? [] : [unencrypted]),
        ...(auth.privateKeyPassword ? [auth.privateKeyPassword.value] : []),
      ];
    }
  }
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

// What an HTTP Basic `Authorization` header carries, so the encoded pair is redacted too.
function basicCredentials(username: string, password: string): string {
  return Buffer.from(`${username}:${password}`, 'utf8').toString('base64');
}
