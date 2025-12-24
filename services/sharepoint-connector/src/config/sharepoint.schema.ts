import { z } from 'zod';
import { DEFAULT_GRAPH_RATE_LIMIT_PER_MINUTE } from '../constants/defaults.constants';
import { IngestionMode } from '../constants/ingestion.constants';
import { StoreInternallyMode } from '../constants/store-internally-mode.enum';
import { Redacted } from '../utils/redacted';

const oidcAuthModeConfig = z.object({
  authMode: z.literal('oidc').describe('Authentication mode to use for Microsoft APIs'),
});

const clientSecretAuthModeConfig = z.object({
  authMode: z.literal('client-secret').describe('Authentication mode to use for Microsoft APIs'),
  authClientId: z.string().nonempty().describe('Azure AD application client ID'),
  authClientSecret: z
    .string()
    .nonempty()
    .transform((val) => new Redacted(val))
    .describe('Azure AD application client secret for Microsoft APIs'),
});

const certificateAuthModeConfig = z
  .object({
    authMode: z.literal('certificate').describe('Authentication mode to use for Microsoft APIs'),
    authClientId: z.string().nonempty().describe('Azure AD application client ID'),
    authThumbprintSha1: z
      .hex()
      .nonempty()
      .optional()
      .describe('SHA1 thumbprint of the Azure AD application certificate'),
    authThumbprintSha256: z
      .hex()
      .nonempty()
      .optional()
      .describe('SHA256 thumbprint of the Azure AD application certificate'),
    authPrivateKeyPath: z
      .string()
      .nonempty()
      .describe(
        'Path to the private key file of the Azure AD application certificate in PEM format',
      ),
    // authPrivateKeyPassword is NOT in YAML - loaded from SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD environment variable (if needed)
  })
  .refine((config) => config.authThumbprintSha1 || config.authThumbprintSha256, {
    message:
      'Either SHAREPOUNT_AUTH_THUMBPRINT_SHA1 or SHAREPOUNT_AUTH_THUMBPRINT_SHA256 has to be provided for certificate authentication mode',
  });

const SiteConfigSchema = z.object({
  siteId: z.uuidv4().describe('SharePoint site ID'),
  syncColumnName: z
    .string()
    .prefault('FinanceGPTKnowledge')
    .describe('Name of the SharePoint column indicating sync flag'),
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
  maxIngestedFiles: z.coerce
    .number()
    .int()
    .positive()
    .optional()
    .describe(
      'Maximum number of files to ingest for this site in a single run. If the number of new + updated files exceeds this limit, the sync for this site will fail.',
    ),
  storeInternally: z
    .enum([StoreInternallyMode.Enabled, StoreInternallyMode.Disabled])
    .default(StoreInternallyMode.Enabled)
    .describe('Whether to store content internally in Unique or not.'),
  syncStatus: z
    .enum(['active', 'inactive', 'deleted'])
    .default('active')
    .describe(
      'Sync status: active = sync this site, inactive = skip this site, deleted = skip this site',
    ),
  syncMode: z
    .enum(['content_only', 'content_and_permissions'])
    .describe(
      'Mode of synchronization from SharePoint to Unique. ' +
        'content_only: sync only the content, ' +
        'content_and_permissions: sync both content and permissions',
    ),
});

export type SiteConfig = z.infer<typeof SiteConfigSchema>;

const baseConfig = z.object({
  authTenantId: z.string().min(1).describe('Azure AD tenant ID'),
  graphApiRateLimitPerMinute: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_GRAPH_RATE_LIMIT_PER_MINUTE)
    .describe('Number of MS Graph API requests allowed per minute'),
  baseUrl: z
    .url()
    .refine((url) => !url.endsWith('/'), {
      message: 'Base URL must not end with a trailing slash',
    })
    .describe("Your company's sharepoint URL"),
  sites: z
    .array(SiteConfigSchema)
    .min(1, 'At least one site must be configured')
    .describe('Array of SharePoint sites to sync'),
});

export const SharepointConfigSchema = z
  .discriminatedUnion('authMode', [
    oidcAuthModeConfig,
    clientSecretAuthModeConfig,
    certificateAuthModeConfig,
  ])
  .and(baseConfig);

export type SharepointConfigYaml = z.infer<typeof SharepointConfigSchema>;

// Type for the final config with secrets injected from environment
export type SharepointConfig = SharepointConfigYaml & {
  authPrivateKeyPassword?: string;
};
