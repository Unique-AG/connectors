import { ConfigType } from '@nestjs/config';
import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE } from '../constants/defaults.constants';
import { IngestionMode } from '../constants/ingestion.constants';
import { parseJsonEnvironmentVariable } from '../utils/config.util';
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

const baseConfig = z
  .object({
    ingestionMode: z
      .enum([IngestionMode.Flat, IngestionMode.Recursive] as const)
      .describe(
        'Ingestion mode: FLAT ingests all files to a single root scope, RECURSIVE maintains the folder hierarchy (path-based ingestion).',
      ),
    scopeId: z
      .string()
      .optional()
      .describe(
        'Scope ID for FLAT ingestion mode. Required when ingestionMode is FLAT. Leave undefined for RECURSIVE mode (path-based ingestion).',
      ),
    rootScopeName: z
      .string()
      .optional()
      .describe(
        'Used only in case of Recursive ingestion mode. Indicates the name of the root scope/folder in the knowledge base where SharePoint content should be synced.',
      ),
    ingestionGraphqlUrl: z.url().describe('Unique graphql ingestion service URL'),
    // TODO: Right now scopeManagementGraphqlUrl is required, but in the future it should be
    //       optional based on the sync mode, but it lives in processing config.
    scopeManagementGraphqlUrl: z.url().describe('Unique graphql scope management service URL'),
    fileDiffUrl: z.url().describe('Unique file diff service URL'),
    apiRateLimitPerMinute: z.coerce
      .number()
      .int()
      .positive()
      .prefault(DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE)
      .describe('Number of Unique API requests allowed per minute'),
    maxIngestedFiles: z.coerce
      .number()
      .int()
      .nonnegative()
      .optional()
      .describe(
        'Maximum number of files to ingest in a single run. If the number of new + updated files exceeds this limit, the sync will fail.',
      ),
  })
  .refine((config) => config.ingestionMode === IngestionMode.Recursive || config.scopeId, {
    message: 'scopeId is required for FLAT ingestion mode',
    path: ['scopeId'],
  });

const UniqueConfig = z
  .discriminatedUnion('serviceAuthMode', [clusterLocalConfig, externalConfig])
  .and(baseConfig);

export const uniqueConfig = registerConfig('unique', UniqueConfig, {
  whitelistKeys: new Set([
    'ZITADEL_OAUTH_TOKEN_URL',
    'ZITADEL_PROJECT_ID',
    'ZITADEL_CLIENT_ID',
    'ZITADEL_CLIENT_SECRET',
  ]),
});

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
