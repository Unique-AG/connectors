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
      'disabled',
    ),
    liveCatchupOverlappingWindowMinutes: z.coerce
      .number()
      // During our tests we noticed that if a user with a lot of emails in their inbox drags and drops a bunch of emails in another folder
      // we will lose this emails. This is because office365 is a distributed system and the rely on eventul concistency which means. You
      // can query via {{updatedAt}} le {someDate} and get 5 messages but and in the next second you query again and you get 10 messages
      // because the server which process the message stamps the {{updatedAt}} it sounds totally stupid but this is how they do it, they
      // rely on eventual concistency and they advise monitoring each folder which is just madness for our case. So an overlapping window
      // is advised if you use dates for high polling. The problem with this is that we do not know how much we need to put here a short
      // chat with claude about this yealded nothing claude says this should be something small max to be minutes. Gemini on the other hand
      // suggested something like this:
      // 1.  60 seconds if you agree to lose some messages
      // 2. 2-3 minutes you will get almost all messages it's a very low chance to lose anything
      // 3.   5 minutes you are 99% you get everything if there are big outages you will probably lose some messages but the change is quite low
      .min(2)
      .prefault(3)
      .describe('How many minutes should each live catchup run overlap the previous one'),
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
    'LIVE_CATCHUP_OVERLAPPING_WINDOW_MINUTES',
  ]),
});

export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;
export type AppConfig = ConfigType<typeof appConfig>;
