import { ConfigType } from '@nestjs/config';
import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE } from '../constants/defaults.constants';
import { IngestionMode } from '../constants/ingestion.constants';
import { parseJsonEnvironmentVariable } from '../utils/config.util';
import { Redacted } from '../utils/redacted';

const UniqueConfig = z
  .object({
    ingestionMode: z
      .enum([IngestionMode.Flat, IngestionMode.Recursive, IngestionMode.RecursiveAdvanced] as const)
      .describe(
        'Ingestion mode: FLAT ingests all files to a single root scope, RECURSIVE maintains the folder hierarchy (path-based ingestion), RECURSIVE_ADVANCED creates explicit scope hierarchy via Scope Management service.',
      ),
    scopeId: z
      .string()
      .optional()
      .describe(
        'Scope ID for FLAT ingestion mode. Required when ingestionMode is FLAT. Leave undefined for RECURSIVE or RECURSIVE_ADVANCED modes.',
      ),
    rootScopeName: z
      .string()
      .optional()
      .describe(
        'Used only in case of Recursive ingestion mode. Indicates the name of the root scope/folder in the knowledge base where SharePoint content should be synced.',
      ),
    ingestionScopeLocation: z
      .string()
      .optional()
      .describe(
        'Required for RECURSIVE_ADVANCED mode. Base scope path where files will be ingested (e.g., "Company/SharePoint" or "SharePoint").',
      ),
    ingestionGraphqlUrl: z.url().describe('Unique graphql ingestion service URL'),
    // TODO: Right now scopeManagementGraphqlUrl is required, but in the future it should be
    //       optional based on the sync mode, but it lives in processing config.
    scopeManagementGraphqlUrl: z.url().describe('Unique graphql scope management service URL'),
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
        'JSON string of extra HTTP headers for ingestion API requests (e.g., {"x-service-id": "<client-id>", "x-company-id": "<company-id>", "x-user-id": "<user-id>"})',
      ),
  })
  .refine((config) => config.ingestionMode === IngestionMode.Recursive || config.scopeId, {
    message: 'scopeId is required for FLAT ingestion mode',
    path: ['scopeId'],
  });

export const uniqueConfig = registerConfig('unique', UniqueConfig);

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
