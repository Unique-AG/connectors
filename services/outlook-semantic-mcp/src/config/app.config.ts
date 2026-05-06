import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { enabledDisabledBoolean, stringToURL } from '~/utils/zod';
import { delegatedAccessConfig } from './app/mcpDelegatedAccess.config';
import { mcpIngestionConfig } from './app/mcpIngestion.config';

export const mcpDebugModeSchema = enabledDisabledBoolean(
  `Enables debug mode. In debug mode tools responses contain debugging data.`,
  'disabled',
);

export const mcpBackendSchema = z
  .enum(['MicrosoftGraphAndUniqueApi', 'MicrosoftGraph'])
  .prefault('MicrosoftGraphAndUniqueApi')
  .describe(
    'Selects the search backend: MicrosoftGraphAndUniqueApi (KB ingestion) or MicrosoftGraph (direct Graph search).',
  );

const mcpMicrosoftGraphBackendConfig = z.object({
  mcpBackend: z.literal('MicrosoftGraph'),
});

const mcpBackendConfig = z.discriminatedUnion('mcpBackend', [
  mcpMicrosoftGraphBackendConfig,
  mcpIngestionConfig,
]);

const commonSchema = z
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
    mcpDebugMode: mcpDebugModeSchema,
    directorySyncCronSchedule: z
      .string()
      .prefault('*/5 * * * *')
      .describe('Cron schedule for delegated access discovery. Default: every 5 minutes'),
  })
  .transform((c) => ({
    ...c,
    isDev: c.nodeEnv === 'development',
    isDebuggingOn: c.logLevel === 'debug' || c.logLevel === 'trace',
  }));

const ConfigSchema = commonSchema
  .and(delegatedAccessConfig)
  .and(mcpBackendConfig)
  .superRefine((data, ctx) => {
    if (data.mcpBackend === 'MicrosoftGraph' && data.delegatedAccessScan === 'granularAccess') {
      ctx.addIssue({
        code: 'custom',
        message:
          '`granularAccess` is not supported with the `MicrosoftGraph` backend; use `fullAccessOnly` or `disabled`',
        path: ['delegatedAccessScan'],
      });
    }
  });

export const appConfig = registerConfig('app', ConfigSchema, {
  whitelistKeys: new Set([
    'LOG_LEVEL',
    'PORT',
    'NODE_ENV',
    'SELF_URL',
    'MCP_DEBUG_MODE',
    'MCP_BACKEND',
    'DIRECTORY_SYNC_CRON_SCHEDULE',
    // Delegated access
    'DELEGATED_ACCESS_SCAN',
    'DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE',
    'DELEGATED_ACCESS_VERIFICATION_CRON_SCHEDULE',
    // Ingestion backend (MicrosoftGraphAndUniqueApi)
    'INGESTION_DEFAULT_MAIL_FILTERS',
    'INGESTION_LIVE_CATCHUP_OVERLAPPING_WINDOW_MINUTES',
    'INGESTION_LIVE_CATCHUP_RECHECK_OVERLAPPING_WINDOW_MINUTES',
    'INGESTION_FULL_SYNC_RECOVERY_CRON',
    'INGESTION_LIVE_CATCHUP_RECOVERY',
    'INGESTION_DELETE_INBOX_RECOVERY_CRON',
  ]),
});

export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;
export type AppConfig = ConfigType<typeof appConfig>;
