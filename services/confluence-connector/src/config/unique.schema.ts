import { z } from 'zod';
import { DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE } from '../constants/defaults.constants';
import { createSmeared, type Smeared } from '../utils/smeared';
import {
  coercedPositiveIntSchema,
  redactedNonEmptyStringSchema,
  urlWithoutTrailingSlashSchema,
} from '../utils/zod.util';

// TODO: Confirm smearing policy with #sig-security-compliance
const SMEARED_HEADER_KEYS = new Map<string, boolean>([
  ['x-company-id', true],
  ['x-user-id', true],
]);

const clusterLocalConfig = z.object({
  serviceAuthMode: z
    .literal('cluster_local')
    .describe('Authentication mode to use for accessing Unique API services'),
  serviceExtraHeaders: z
    .record(z.string(), z.string())
    .refine(
      (headers) => {
        const providedHeaders = Object.keys(headers);
        const requiredHeaders = ['x-company-id', 'x-user-id'];
        return requiredHeaders.every((header) => providedHeaders.includes(header));
      },
      {
        message: 'serviceExtraHeaders must contain x-company-id and x-user-id headers',
        path: ['serviceExtraHeaders'],
      },
    )
    .transform((headers) => {
      const result: Record<string, string | Smeared> = {};
      for (const [key, value] of Object.entries(headers)) {
        result[key] = SMEARED_HEADER_KEYS.has(key) ? createSmeared(value) : value;
      }
      return result;
    })
    .describe(
      `String of extra HTTP headers for ingestion API requests (e.g., {"x-company-id": "<company-id>", "x-user-id": "<user-id>"})`,
    ),
});

const externalConfig = z.object({
  serviceAuthMode: z
    .literal('external')
    .describe('Authentication mode to use for accessing Unique API services'),
  zitadelOauthTokenUrl: z.url().describe('Zitadel login token'),
  zitadelProjectId: redactedNonEmptyStringSchema.describe('Zitadel project ID'),
  zitadelClientId: z.string().describe('Zitadel client ID'),
  zitadelClientSecret: redactedNonEmptyStringSchema.describe(
    'Zitadel client secret (injected from ZITADEL_CLIENT_SECRET environment variable)',
  ),
});

const uniqueBaseConfig = z.object({
  ingestionServiceBaseUrl: urlWithoutTrailingSlashSchema(
    'Base URL for Unique ingestion service',
    'ingestionServiceBaseUrl must not end with a trailing slash',
  ),
  scopeManagementServiceBaseUrl: urlWithoutTrailingSlashSchema(
    'Base URL for Unique scope management service',
    'scopeManagementServiceBaseUrl must not end with a trailing slash',
  ),
  apiRateLimitPerMinute: coercedPositiveIntSchema
    .prefault(DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE)
    .describe('Number of Unique API requests allowed per minute'),
  ingestionConfig: z
    .record(z.string(), z.unknown())
    .optional()
    .describe(
      `Config object to pass when submitting file for ingestion (e.g., {"uniqueIngestionMode": "SKIP_INGESTION", "customProperty": "value"})`,
    ),
});

export const UniqueConfigSchema = z
  .discriminatedUnion('serviceAuthMode', [clusterLocalConfig, externalConfig])
  .and(uniqueBaseConfig);

export type UniqueConfig = z.infer<typeof UniqueConfigSchema>;
