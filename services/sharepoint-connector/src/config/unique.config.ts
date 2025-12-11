import { ConfigType } from '@nestjs/config';
import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE } from '../constants/defaults.constants';
import { IngestionMode } from '../constants/ingestion.constants';
import { StoreInternallyMode } from '../constants/store-internally-mode.enum';
import { parseJsonEnvironmentVariable } from '../utils/config.util';
import { INHERITANCE_PRESETS } from '../utils/inheritance.constants';
import { Redacted } from '../utils/redacted';

// ==== Config for local in-cluster communication with Unique API services ====

const clusterLocalConfig = z.object({
  serviceAuthMode: z
    .literal('cluster_local')
    .describe('Authentication mode to use for accessing Unique API services'),
  serviceExtraHeaders: z
    .string()
    .pipe(parseJsonEnvironmentVariable('UNIQUE_SERVICE_EXTRA_HEADERS'))
    .refine(
      (headers) => {
        const providedHeaders = Object.keys(headers);
        const requiredHeaders = ['x-company-id', 'x-user-id'];
        return requiredHeaders.every((header) => providedHeaders.includes(header));
      },
      {
        message: 'UNIQUE_SERVICE_EXTRA_HEADERS must contain x-company-id and x-user-id headers',
        path: ['serviceExtraHeaders'],
      },
    )
    .describe(
      'JSON string of extra HTTP headers for ingestion API requests ' +
        '(e.g., {"x-company-id": "<company-id>", "x-user-id": "<user-id>"})',
    ),
});

// ==== Config for external communication with Unique API services via Zitadel authentication ====

const externalConfig = z.object({
  serviceAuthMode: z
    .literal('external')
    .describe('Authentication mode to use for accessing Unique API services'),
  zitadelOauthTokenUrl: z.url().describe('Zitadel login token'),
  zitadelProjectId: z.string().describe('Zitadel project ID'),
  zitadelClientId: z.string().describe('Zitadel client ID'),
  zitadelClientSecret: z
    .string()
    .transform((val) => new Redacted(val))
    .describe('Zitadel client secret'),
});

// ==== Config common for both cluster_local and external authentication modes ====

const baseConfig = z.object({
  permissionsInheritanceMode: z
    .enum(['inherit_scopes_and_files', 'inherit_scopes', 'inherit_files', 'none'] as const)
    .default('inherit_scopes_and_files')
    .transform((mode) => INHERITANCE_PRESETS[mode])
    .describe(
      'Inheritance mode for generated scopes and ingested files in content_only mode; ignored in content_and_permissions mode. Allowed values: inherit_scopes_and_files, inherit_scopes, inherit_files, none.',
    ),
  ingestionMode: z
    .enum([IngestionMode.Flat, IngestionMode.Recursive] as const)
    .describe(
      'Ingestion mode: flat ingests all files to a single root scope, recursive maintains the folder hierarchy.',
    ),
  scopeId: z
    .string()
    .describe(
      'Scope ID to be used as root for ingestion. For flat mode, all files are ingested in this scope. For recursive mode, this is the root scope where SharePoint content hierarchy starts.',
    ),
  ingestionServiceBaseUrl: z
    .url()
    .describe('Base URL for Unique ingestion service')
    .refine((url) => !url.endsWith('/'), {
      message: 'ingestionServiceBaseUrl must not end with a trailing slash',
    }),
  // TODO: Right now scopeManagementServiceBaseUrl is required, but in the future it should be
  //       optional based on the sync mode, but it lives in processing config.
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
  maxIngestedFiles: z.coerce
    .number()
    .int()
    .positive()
    .optional()
    .describe(
      'Maximum number of files to ingest per site in a single run. If the number of new + updated files for a site exceeds this limit, the sync for that site will fail.',
    ),
  storeInternally: z
    .enum([StoreInternallyMode.Enabled, StoreInternallyMode.Disabled])
    .default(StoreInternallyMode.Disabled)
    .describe('Whether to store content internally in Unique or not.'),
  ingestionConfig: z
    .string()
    .pipe(parseJsonEnvironmentVariable('UNIQUE_INGESTION_CONFIG'))
    .optional()
    .describe(
      'JSON string of config to pass when submitting file for ingestion (e.g., ' +
        '{"uniqueIngestionMode": "SKIP_INGESTION", "customProperty": "value"})',
    ),
});

export const UniqueConfigSchema = z
  .discriminatedUnion('serviceAuthMode', [clusterLocalConfig, externalConfig])
  .and(baseConfig);

export const uniqueConfig = registerConfig('unique', UniqueConfigSchema, {
  whitelistKeys: new Set([
    'ZITADEL_OAUTH_TOKEN_URL',
    'ZITADEL_PROJECT_ID',
    'ZITADEL_CLIENT_ID',
    'ZITADEL_CLIENT_SECRET',
  ]),
});

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
