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

const patAuth = z.object({
  mode: z.literal('pat'),
  token: redactedNonEmptyStringSchema,
});

const baseConfluenceFields = z.object({
  baseUrl: urlWithoutTrailingSlashSchema(
    'Base URL of the Confluence instance',
    'baseUrl must not end with a trailing slash',
  ),
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
});

export const ConfluenceConfigSchema = z.discriminatedUnion('instanceType', [
  baseConfluenceFields.extend({
    instanceType: z.literal('cloud'),
    auth: oauth2loAuth,
  }),
  baseConfluenceFields.extend({
    instanceType: z.literal('data-center'),
    auth: z.discriminatedUnion('mode', [oauth2loAuth, patAuth]),
  }),
]);

export type ConfluenceConfig = z.infer<typeof ConfluenceConfigSchema>;
