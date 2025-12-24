import { z } from 'zod';
import { DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE } from '../constants/defaults.constants';
import { Redacted } from '../utils/redacted';

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
    .describe(
      'string of extra HTTP headers for ingestion API requests ' +
        '(e.g., {"x-company-id": "<company-id>", "x-user-id": "<user-id>"})',
    ),
});

const externalConfig = z.object({
  serviceAuthMode: z
    .literal('external')
    .describe('Authentication mode to use for accessing Unique API services'),
  zitadelOauthTokenUrl: z.url().describe('Zitadel login token'),
  zitadelProjectId: z.string().describe('Zitadel project ID'),
  zitadelClientId: z.string().describe('Zitadel client ID'),
  // zitadelClientSecret is NOT in YAML - loaded from ZITADEL_CLIENT_SECRET environment variable
});

const baseConfig = z.object({
  ingestionServiceBaseUrl: z
    .url()
    .describe('Base URL for Unique ingestion service')
    .refine((url) => !url.endsWith('/'), {
      message: 'ingestionServiceBaseUrl must not end with a trailing slash',
    }),
  scopeManagementServiceBaseUrl: z
    .url()
    .describe('Base URL for Unique scope management service')
    .refine((url) => !url.endsWith('/'), {
      message: 'scopeManagementServiceBaseUrl must not end with a trailing slash',
    }),
  apiRateLimitPerMinute: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE)
    .describe('Number of Unique API requests allowed per minute'),
  ingestionConfig: z
    .record(z.string(), z.unknown())
    .optional()
    .describe(
      'Config object to pass when submitting file for ingestion (e.g., ' +
        '{"uniqueIngestionMode": "SKIP_INGESTION", "customProperty": "value"})',
    ),
});

export const UniqueConfigSchema = z
  .discriminatedUnion('serviceAuthMode', [clusterLocalConfig, externalConfig])
  .and(baseConfig);

export type UniqueConfigYaml = z.infer<typeof UniqueConfigSchema>;

// Type for the final config with secrets injected from environment
export type UniqueConfig = UniqueConfigYaml & {
  zitadelClientSecret?: Redacted<string>;
};
