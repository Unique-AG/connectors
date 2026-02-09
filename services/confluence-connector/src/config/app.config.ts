import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';

export const LogsDiagnosticDataPolicy = {
  CONCEAL: 'conceal',
  DISCLOSE: 'disclose',
} as const;

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
      .prefault(51347)
      .describe('The local HTTP port to bind the server to'),
    logLevel: z
      .enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent'])
      .prefault('info')
      .describe('The log level at which the services outputs (pino)'),
    logsDiagnosticsDataPolicy: z
      .enum(LogsDiagnosticDataPolicy)
      .prefault(LogsDiagnosticDataPolicy.CONCEAL)
      .describe(
        'Controls whether sensitive data e.g. emails, usernames, etc. are logged in full or smeared',
      ),
  })
  .transform((c) => ({
    ...c,
    isDev: c.nodeEnv === 'development',
  }));

export const appConfig = registerConfig('app', AppConfigSchema, {
  whitelistKeys: new Set(['LOG_LEVEL', 'PORT', 'NODE_ENV', 'LOGS_DIAGNOSTICS_DATA_POLICY']),
});

export type AppConfig = ConfigType<typeof appConfig>;
export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;
