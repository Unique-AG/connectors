import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';

const ConfigSchema = z
  .object({
    nodeEnv: z
      .enum(['development', 'production', 'test'])
      .default('production')
      .describe('Specifies the environment in which the application is running'),
    port: z
      .number()
      .int()
      .min(0)
      .max(65535)
      .default(9541)
      .describe('The local HTTP port to bind the server to'),
    logLevel: z
      .enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent'])
      .default('info')
      .describe('The log level at which the services outputs (pino)'),
  })
  .transform((c) => ({
    ...c,
    isDev: c.nodeEnv === 'development',
  }));

export const appConfig = registerConfig('app', ConfigSchema, {
  whitelistKeys: new Set(['LOG_LEVEL', 'PORT', 'NODE_ENV']),
});

export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;
export type AppConfig = ConfigType<typeof appConfig>;
