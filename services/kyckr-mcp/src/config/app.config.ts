import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { enabledDisabledBoolean, redacted } from '~/utils/zod';

const ConfigSchema = z
  .object({
    bufferLogs: enabledDisabledBoolean('If the nestjs app should buffer the logs on startup.'),
    nodeEnv: z
      .enum(['development', 'production', 'test'])
      .prefault('production')
      .describe('The environment in which the application is running.'),
    port: z.coerce
      .number()
      .int()
      .min(0)
      .max(65535)
      .prefault(9542)
      .describe('The local HTTP port to bind the server to.'),
    logLevel: z
      .enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent'])
      .prefault('info')
      .describe('The log level at which the services outputs (pino).'),
    mcpAccessToken: redacted(z.string()).describe(
      'Shared secret protecting the /mcp endpoint. Requests must supply it as a Bearer token in the Authorization header.',
    ),
  })
  .transform((c) => ({
    ...c,
    isDev: c.nodeEnv === 'development',
  }));

export const appConfig = registerConfig('app', ConfigSchema, {
  whitelistKeys: new Set(['LOG_LEVEL', 'PORT', 'NODE_ENV', 'MCP_ACCESS_TOKEN']),
});

export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;
export type AppConfig = ConfigType<typeof appConfig>;
