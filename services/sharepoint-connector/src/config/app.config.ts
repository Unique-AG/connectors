import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';

// ==========================================
// App Configuration
// ==========================================

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
      .enum(['conceal', 'disclose'])
      .prefault('conceal')
      .describe(
        'Controls whether sensitive data e.g. site names, file names, etc. are logged in full or redacted',
      ),
    tenantConfigPathPattern: z
      .string()
      .nonempty()
      .describe(
        'Path pattern to tenant configuration YAML file(s). Supports glob patterns (e.g., /app/config/*-tenant-config.yaml)',
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
    'TENANT_CONFIG_PATH_PATTERN',
  ]),
});

export type AppConfig = ConfigType<typeof appConfig>;
export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;
