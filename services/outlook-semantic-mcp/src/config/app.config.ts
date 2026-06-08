import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { enabledDisabledBoolean, stringToURL } from '~/utils/zod';
import { mcpBackendSchema } from './mcp-backend-type.config';

export const mcpDebugModeSchema = enabledDisabledBoolean(
  `Enables debug mode. In debug mode tools responses contain debugging data.`,
  'disabled',
);

const ConfigSchema = z
  .object({
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
    selfUrl: stringToURL().describe('The URL of the MCP Server. Used for OAuth callbacks.'),
    mcpDebugMode: mcpDebugModeSchema,
    mcpBackend: mcpBackendSchema,
    directorySyncCronSchedule: z
      .string()
      .prefault('*/5 * * * *')
      .describe(
        'Cron schedule for syncing mail folder structure for all active subscriptions. Default: every 5 minutes.',
      ),
  })
  .transform((c) => ({
    ...c,
    isDev: c.nodeEnv === 'development',
    isDebuggingOn: c.logLevel === 'debug' || c.logLevel === 'trace',
  }));

export const appConfig = registerConfig('app', ConfigSchema, {
  whitelistKeys: new Set([
    'LOG_LEVEL',
    'PORT',
    'NODE_ENV',
    'SELF_URL',
    'MCP_DEBUG_MODE',
    'MCP_BACKEND',
    'DIRECTORY_SYNC_CRON_SCHEDULE',
  ]),
});

export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;
export type AppConfig = ConfigType<typeof appConfig>;
