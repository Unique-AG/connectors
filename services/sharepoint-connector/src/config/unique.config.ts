import { ConfigType } from '@nestjs/config';
import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE } from '../constants/defaults.constants';
import { IngestionMode } from '../constants/ingestion.constants';
import { Redacted } from '../utils/redacted';

const UniqueConfig = z
  .object({
    uniqueApiVersion: z
      .enum(['v44', 'v46'])
      .prefault('v46')
      .describe(
        'Unique API version. V44 does not support rootScope and structuredPath. V46 and later support these features for proper scope and path-based ingestion.',
      ),
    ingestionMode: z
      .enum([IngestionMode.Flat, IngestionMode.Recursive] as const)
      .default(IngestionMode.Recursive)
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
        'Name of the root scope/folder in the knowledge base where SharePoint content should be synced. Used with both FLAT and RECURSIVE ingestion modes.',
      ),
    rootScopeId: z
      .string()
      .optional()
      .describe(
        'Existing scope ID for RECURSIVE (path-based) ingestion. When provided, all files will be ingested in this scope instead of creating new scopes.',
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
  })
  .refine(
    (config) => config.ingestionMode === IngestionMode.Recursive || config.scopeId,
    {
      message: 'scopeId is required when ingestionMode is FLAT',
      path: ['scopeId'],
    },
  );

export const uniqueConfig = registerConfig('unique', UniqueConfig);

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
