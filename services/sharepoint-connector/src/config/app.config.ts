import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { requiredStringSchema } from '../utils/zod.util';

// ==========================================
// App Configuration
// ==========================================

export const LogsDiagnosticDataPolicy = {
  CONCEAL: 'conceal',
  DISCLOSE: 'disclose',
} as const;

export const ConfigEmitPolicy = {
  ON_STARTUP: 'on_startup',
  PER_SYNC: 'per_sync',
} as const;
export type ConfigEmitPolicyType = (typeof ConfigEmitPolicy)[keyof typeof ConfigEmitPolicy];

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
      .enum(LogsDiagnosticDataPolicy)
      .prefault(LogsDiagnosticDataPolicy.CONCEAL)
      .describe(
        'Controls whether sensitive data e.g. site names, file names, etc. are logged in full or redacted',
      ),
    logsDiagnosticsConfigEmitPolicy: z
      .union([z.literal('none'), z.array(z.enum(ConfigEmitPolicy))])
      .prefault([ConfigEmitPolicy.ON_STARTUP, ConfigEmitPolicy.PER_SYNC])
      .describe(
        'Controls when configuration is logged. Array of triggers: on_startup logs once on start, per_sync logs at each site sync. Use "none" to disable.',
      ),
    tenantConfigPathPattern: requiredStringSchema.describe(
      'Path pattern to tenant configuration YAML file(s). Supports glob patterns (e.g., /app/tenant-configs/*-tenant-config.yaml)',
    ),
  })
  .transform((c) => ({
    ...c,
    isDev: c.nodeEnv === 'development',
  }));

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
