import { z } from 'zod';
import {
  DEFAULT_CONFLUENCE_API_RATE_LIMIT_PER_MINUTE,
  DEFAULT_INGEST_ALL_LABEL,
  DEFAULT_INGEST_SINGLE_LABEL,
} from '../constants/defaults.constants';
import {
  coercedPositiveIntSchema,
  redactedNonEmptyStringSchema,
  urlWithoutTrailingSlashSchema,
} from '../utils/zod.util';

const oauth2loAuth = z.object({
  mode: z.literal('oauth_2lo'),
  clientId: z.string().min(1),
  clientSecret: redactedNonEmptyStringSchema,
});

export const ConfluenceConfigSchema = z.object({
  instanceType: z
    .enum(['cloud', 'data-center'])
    .describe('Type of Confluence instance (cloud or data-center)'),
  baseUrl: urlWithoutTrailingSlashSchema(
    'Base URL of the Confluence instance',
    'baseUrl must not end with a trailing slash',
  ),
  auth: z.discriminatedUnion('mode', [oauth2loAuth]),
  apiRateLimitPerMinute: coercedPositiveIntSchema
    .prefault(DEFAULT_CONFLUENCE_API_RATE_LIMIT_PER_MINUTE)
    .describe('Number of Confluence API requests allowed per minute'),
  ingestSingleLabel: z
    .string()
    .prefault(DEFAULT_INGEST_SINGLE_LABEL)
    .describe('Label to trigger single-page sync'),
  ingestAllLabel: z
    .string()
    .prefault(DEFAULT_INGEST_ALL_LABEL)
    .describe('Label to trigger full sync of all labeled pages'),
  spaces: z
    .array(z.string())
    .optional()
    .describe('Space keys to sync (if empty, syncs all accessible spaces)'),
});

export type ConfluenceConfig = z.infer<typeof ConfluenceConfigSchema>;
