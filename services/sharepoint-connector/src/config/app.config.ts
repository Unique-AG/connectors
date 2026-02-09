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

export const ConfigEmitEvent = {
  ON_STARTUP: 'on_startup',
  PER_SYNC: 'per_sync',
} as const;
export type ConfigEmitEventType = (typeof ConfigEmitEvent)[keyof typeof ConfigEmitEvent];

const allConfigEmitEvents = [ConfigEmitEvent.ON_STARTUP, ConfigEmitEvent.PER_SYNC] as const;

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
      .preprocess(
        (val) => (typeof val === 'string' ? JSON.parse(val) : val),
        z.discriminatedUnion('emit', [
          z.object({
            emit: z.literal('on'),
            events: z.array(z.enum(ConfigEmitEvent)).nonempty(),
          }),
          z.object({
            emit: z.literal('off'),
          }),
        ]),
      )
      .prefault({ emit: 'on' as const, events: [...allConfigEmitEvents] })
      .describe(
        'Controls when configuration is logged. Object with emit: "on"/"off". When "on", events array is required and must contain at least one of: on_startup, per_sync.',
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
