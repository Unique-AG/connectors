import { ConfigType } from '@nestjs/config';
import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE } from '../constants/defaults.constants';
import { parseJsonEnvironmentVariable } from '../utils/config.util';
import { Redacted } from '../utils/redacted';

const UniqueConfig = z.object({
  scopeId: z
    .string()
    .optional()
    .describe(
      'Controls if you are using path based ingestion or scope based ingestion. Leave undefined for PATH based ingestion. Add your scope id for scope based ingestion.',
    ),
  ingestionGraphqlUrl: z.url().describe('Unique graphql ingestion service URL'),
  fileDiffUrl: z.url().describe('Unique file diff service URL'),
  zitadelOauthTokenUrl: z.url().describe('Zitadel login token'),
  zitadelProjectId: z.string().describe('Zitadel project ID'),
  zitadelClientId: z.string().describe('Zitadel client ID'),
  zitadelClientSecret: z
    .string()
    .transform((val) => new Redacted(val))
    .describe('Zitadel client secret'),
  apiRateLimitPerMinute: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE)
    .describe('Number of Unique API requests allowed per minute'),
  zitadelHttpExtraHeaders: z
    .string()
    .optional()
    .prefault('')
    .pipe(parseJsonEnvironmentVariable('zitadelHttpExtraHeaders'))
    .describe(
      'JSON string of extra HTTP headers for Zitadel requests (e.g., {"x-zitadel-instance-host": "<zitadel-host>"})',
    ),
  httpExtraHeaders: z
    .string()
    .optional()
    .prefault('')
    .pipe(parseJsonEnvironmentVariable('httpExtraHeaders'))
    .describe(
      'JSON string of extra HTTP headers for ingestion API requests (e.g., {"x-client-id": "<client-id>", "x-company-id": "<company-id>", "x-user-id": "<user-id>"})',
    ),
});

export const uniqueConfig = registerConfig('unique', UniqueConfig);

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
