import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { requiredStringSchema } from '../utils/zod.util';

// ==========================================
// App Configuration
// ==========================================

export const LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME = 'LOGS_DIAGNOSTICS_DATA_POLICY';

export enum LogsDiagnosticDataPolicy {
  CONCEAL = 'conceal',
  DISCLOSE = 'disclose',
}

export const AppConfigSchema = z
  .object({
    nodeEnv: z
      .enum(['development', 'production', 'test'])
      .prefault('production')
      .describe('Specifies the environment in which the application is running'),
    port: z.coerce
      .number()
      .int()
      .min(0)
      .max(65535)
      .prefault(9542)
      .describe('The local HTTP port to bind the server to'),
    logLevel: z
      .enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent'])
      .prefault('info')
      .describe('The log level at which the services outputs (pino)'),
    logsDiagnosticsDataPolicy: z
      .nativeEnum(LogsDiagnosticDataPolicy)
      .prefault(LogsDiagnosticDataPolicy.CONCEAL)
      .describe(
        'Controls whether sensitive data e.g. site names, file names, etc. are logged in full or redacted',
      ),
    logsDiagnosticsConfigEmitPolicy: z
      .enum(['on_startup', 'per_sync', 'on_startup_and_per_sync', 'none'])
      .prefault('per_sync')
      .describe(
        'Controls when configuration is logged. on_startup: log once on start, per_sync: log at the beginning of each site sync, on_startup_and_per_sync: log on startup and per sync, none: disable logging.',
      ),
    tenantConfigPathPattern: requiredStringSchema.describe(
      'Path pattern to tenant configuration YAML file(s). Supports glob patterns (e.g., /app/tenant-configs/*-tenant-config.yaml)',
    ),
  })
  .transform((c) => ({
    ...c,
    isDev: c.nodeEnv === 'development',
  }));

export type AppConfigFromSchema = z.infer<typeof AppConfigSchema>;

export const appConfig = registerConfig('app', AppConfigSchema, {
  whitelistKeys: new Set([
    'LOG_LEVEL',
    'PORT',
    'NODE_ENV',
    'LOGS_DIAGNOSTICS_DATA_POLICY',
    'LOGS_DIAGNOSTICS_CONFIG_EMIT_POLICY',
    'TENANT_CONFIG_PATH_PATTERN',
  ]),
});

export type AppConfig = ConfigType<typeof appConfig>;
export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;
