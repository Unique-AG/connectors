import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { inboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { enabledDisabledBoolean, json, stringToURL } from '~/utils/zod';

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
    selfUrl: stringToURL().describe('The URL of the MCP Server. Used for OAuth callbacks.'),
    defaultMailFilters: json(inboxConfigurationMailFilters).describe(
      'Default mail filters applied when syncing emails (e.g. {"ignoredBefore":"2024-01-01", "ignoredSenders": [], "ignoredContents": [] }). ',
    ),
    mcpDebugMode: enabledDisabledBoolean(
      `Enables debug mode. In debug mode tools responses contain debugging data.`,
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
    'DEFAULT_MAIL_FILTERS',
    'MCP_DEBUG_MODE',
  ]),
});

export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;
export type AppConfig = ConfigType<typeof appConfig>;
