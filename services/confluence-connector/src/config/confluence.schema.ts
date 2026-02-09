import { z } from 'zod';
import {
  DEFAULT_CONFLUENCE_API_RATE_LIMIT_PER_MINUTE,
  DEFAULT_INGEST_ALL_LABEL,
  DEFAULT_INGEST_SINGLE_LABEL,
} from '../constants/defaults.constants';
import { createSmeared } from '../utils/smeared';
import {
  coercedPositiveIntSchema,
  redactedNonEmptyStringSchema,
  urlWithoutTrailingSlashSchema,
} from '../utils/zod.util';

const cloudApiTokenAuth = z.object({
  mode: z.literal('api_token'),
  email: z
    .string()
    .email()
    .transform((val) => createSmeared(val)),
  apiToken: redactedNonEmptyStringSchema,
});

const onpremPatAuth = z.object({
  mode: z.literal('pat'),
  token: redactedNonEmptyStringSchema,
});

const onpremBasicAuth = z.object({
  mode: z.literal('basic'),
  username: z.string().transform((val) => createSmeared(val)),
  password: redactedNonEmptyStringSchema,
});

export const ConfluenceConfigSchema = z.object({
  instanceType: z
    .enum(['cloud', 'onprem'])
    .describe('Type of Confluence instance (cloud or on-premises)'),
  baseUrl: urlWithoutTrailingSlashSchema(
    'Base URL of the Confluence instance',
    'baseUrl must not end with a trailing slash',
  ),
  auth: z.discriminatedUnion('mode', [cloudApiTokenAuth, onpremPatAuth, onpremBasicAuth]),
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

export type ConfluenceConfig = z.infer<typeof ConfluenceConfigSchema>;
