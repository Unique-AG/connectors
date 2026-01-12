import { z } from 'zod';
import {
  CRON_EVERY_15_MINUTES,
  DEFAULT_GRAPH_RATE_LIMIT_PER_MINUTE,
  DEFAULT_MAX_FILE_SIZE_BYTES,
  DEFAULT_PROCESSING_CONCURRENCY,
  DEFAULT_STEP_TIMEOUT_SECONDS,
  DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE,
} from '../constants/defaults.constants';
import { IngestionMode } from '../constants/ingestion.constants';
import { StoreInternallyMode } from '../constants/store-internally-mode.enum';
import { Redacted } from '../utils/redacted';

// ==========================================
// 1. Shared Helpers
// ==========================================

/**
 * Creates a URL schema that prevents trailing slashes,
 * which often cause issues with API endpoint concatenation.
 */
const baseUrlSchema = (description: string, message: string) =>
  z
    .url()
    .describe(description)
    .refine((url) => !url.endsWith('/'), { message });

// ==========================================
// 2. Inheritance & Permissions
// ==========================================

export type PermissionsInheritanceMode =
  | 'inherit_scopes_and_files'
  | 'inherit_scopes'
  | 'inherit_files'
  | 'none';

export interface InheritanceSettings {
  inheritScopes: boolean;
  inheritFiles: boolean;
}

export const INHERITANCE_MODES_MAP: Record<PermissionsInheritanceMode, InheritanceSettings> = {
  inherit_scopes_and_files: { inheritScopes: true, inheritFiles: true },
  inherit_scopes: { inheritScopes: true, inheritFiles: false },
  inherit_files: { inheritScopes: false, inheritFiles: true },
  none: { inheritScopes: false, inheritFiles: false },
};

export const PermissionsInheritanceModeSchema = z
  .enum(['inherit_scopes_and_files', 'inherit_scopes', 'inherit_files', 'none'] as const)
  .default('inherit_scopes_and_files')
  .describe(
    'Inheritance mode for generated scopes and ingested files. ' +
      'Only used in content_only sync mode; ignored in content_and_permissions mode. ' +
      'Allowed values: inherit_scopes_and_files, inherit_scopes, inherit_files, none.',
  );

// ==========================================
// 3. SharePoint Configuration
// ==========================================

// --- Auth Modes ---

const oidcAuthConfig = z.object({
  mode: z.literal('oidc').describe('Authentication mode to use for Microsoft APIs'),
});

const clientSecretAuthConfig = z.object({
  mode: z.literal('client-secret').describe('Authentication mode to use for Microsoft APIs'),
  clientId: z.string().nonempty().describe('Azure AD application client ID'),
  clientSecret: z
    .string()
    .nonempty()
    .transform((val) => new Redacted(val))
    .describe('Azure AD application client secret for Microsoft APIs'),
});

const certificateAuthConfig = z
  .object({
    mode: z.literal('certificate').describe('Authentication mode to use for Microsoft APIs'),
    clientId: z.string().nonempty().describe('Azure AD application client ID'),
    thumbprintSha1: z
      .hex()
      .nonempty()
      .optional()
      .describe('SHA1 thumbprint of the Azure AD application certificate'),
    thumbprintSha256: z
      .hex()
      .nonempty()
      .optional()
      .describe('SHA256 thumbprint of the Azure AD application certificate'),
    privateKeyPath: z
      .string()
      .nonempty()
      .describe(
        'Path to the private key file of the Azure AD application certificate in PEM format',
      ),
    privateKeyPassword: z.string().optional(),
  })
  .refine((config) => config.thumbprintSha1 || config.thumbprintSha256, {
    message:
      'Either thumbprintSha1 or thumbprintSha256 has to be provided for certificate authentication mode',
  });

const AuthConfigSchema = z.discriminatedUnion('mode', [
  oidcAuthConfig,
  clientSecretAuthConfig,
  certificateAuthConfig,
]);

// --- Site Configuration ---

export const SiteConfigSchema = z.object({
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
  maxFilesToIngest: z.coerce
    .number()
    .int()
    .positive()
    .optional()
    .describe(
      'Maximum number of files to ingest per site in a single sync run. If the number of new + updated files exceeds this limit, the sync for that site will fail.',
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
  permissionsInheritanceMode: PermissionsInheritanceModeSchema,
});

export type SiteConfig = z.infer<typeof SiteConfigSchema>;

export function getInheritanceSettings({
  syncMode,
  permissionsInheritanceMode,
}: SiteConfig): InheritanceSettings {
  const mode = syncMode === 'content_and_permissions' ? 'none' : permissionsInheritanceMode;
  return INHERITANCE_MODES_MAP[mode];
}

// --- SharePoint Main Schema ---

const staticSitesConfig = z.object({
  sitesSource: z.literal('config_file').describe('Load sites configuration from static YAML array'),
  sites: z
    .array(SiteConfigSchema)
    .min(1, 'At least one site must be configured')
    .describe('Array of SharePoint sites to sync'),
});

const dynamicSitesConfig = z.object({
  sitesSource: z
    .literal('sharepoint_list')
    .describe('Load sites configuration dynamically from SharePoint list'),
  sharepointList: z
    .object({
      siteId: z
        .string()
        .nonempty()
        .describe('SharePoint site ID containing the configuration list'),
      listDisplayName: z
        .string()
        .nonempty()
        .describe('Display name of the SharePoint configuration list'),
    })
    .describe('SharePoint list details containing site configurations'),
});

const sharepointBaseConfig = z.object({
  tenantId: z.string().min(1).describe('Azure AD tenant ID'),
  auth: AuthConfigSchema.describe('Authentication configuration for Microsoft APIs'),
  graphApiRateLimitPerMinute: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_GRAPH_RATE_LIMIT_PER_MINUTE)
    .describe('Number of MS Graph API requests allowed per minute'),
  baseUrl: baseUrlSchema(
    "Your company's sharepoint URL",
    'Base URL must not end with a trailing slash',
  ),
});

export const SharepointConfigSchema = sharepointBaseConfig.and(
  z.discriminatedUnion('sitesSource', [staticSitesConfig, dynamicSitesConfig]),
);

export type AuthConfig = z.infer<typeof AuthConfigSchema>;
export type StaticSitesConfig = z.infer<typeof staticSitesConfig>;
export type DynamicSitesConfig = z.infer<typeof dynamicSitesConfig>;

/**
 * Type for the final SharePoint config with secrets injected from environment.
 * Reconstructs the discriminated union while preserving types for runtime injection.
 */
export type SharepointConfig = (
  | {
      sitesSource: 'config_file';
      sites: StaticSitesConfig['sites'];
    }
  | {
      sitesSource: 'sharepoint_list';
      sharepointList: DynamicSitesConfig['sharepointList'];
    }
) & {
  tenantId: string;
  auth: AuthConfig & {
    privateKeyPassword?: string;
  };
  graphApiRateLimitPerMinute: number;
  baseUrl: string;
};

// ==========================================
// 4. Unique Configuration
// ==========================================

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
  zitadelClientSecret: z.instanceof(Redacted<string>).optional(),
});

const uniqueBaseConfig = z.object({
  ingestionServiceBaseUrl: baseUrlSchema(
    'Base URL for Unique ingestion service',
    'ingestionServiceBaseUrl must not end with a trailing slash',
  ),
  scopeManagementServiceBaseUrl: baseUrlSchema(
    'Base URL for Unique scope management service',
    'scopeManagementServiceBaseUrl must not end with a trailing slash',
  ),
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
  .and(uniqueBaseConfig);

export type UniqueConfigYaml = z.infer<typeof UniqueConfigSchema>;

/**
 * Type for the final Unique config with secrets injected from environment
 */
export type UniqueConfig = UniqueConfigYaml & {
  zitadelClientSecret?: Redacted<string>;
};

// ==========================================
// 5. Processing Configuration
// ==========================================

export const ProcessingConfigSchema = z.object({
  stepTimeoutSeconds: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_STEP_TIMEOUT_SECONDS)
    .describe(
      'Sets a time limit for a file processing step before it will stop and skip processing the file',
    ),
  concurrency: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_PROCESSING_CONCURRENCY)
    .describe('Sets the concurrency of how many files you want to ingest into unique at once'),
  maxFileSizeToIngestBytes: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_MAX_FILE_SIZE_BYTES)
    .describe('Maximum file size in bytes to ingest. Files larger than this will be skipped'),
  allowedMimeTypes: z
    .union([
      z.string().transform((val) =>
        val
          ? val
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : [],
      ),
      z.array(z.string()),
    ])
    .describe('Comma-separated list or array of allowed MIME types for files to sync'),
  maxFilesToScan: z
    .preprocess(
      (val) => (val === '' ? undefined : val),
      z.coerce.number().int().positive().optional(),
    )
    .describe('For testing purpose. Maximum number of files to scan. Unlimited if not set'),
  scanIntervalCron: z
    .string()
    .default(CRON_EVERY_15_MINUTES)
    .describe('Cron expression for the scheduled file scan interval'),
});

export type ProcessingConfig = z.infer<typeof ProcessingConfigSchema>;

// ==========================================
// 6. App Configuration
// ==========================================

export const AppConfigSchema = z
  .object({
    nodeEnv: z
      .enum(['development', 'production', 'test'])
      .prefault('production')
      .describe('Specifies the environment in which the application is running'),
    port: z.coerce
      .number()
      .int()
      .min(0)
      .max(65535)
      .prefault(9542)
      .describe('The local HTTP port to bind the server to'),
    logLevel: z
      .enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent'])
      .prefault('info')
      .describe('The log level at which the services outputs (pino)'),
    logsDiagnosticsDataPolicy: z
      .enum(['conceal', 'disclose'])
      .prefault('conceal')
      .describe(
        'Controls whether sensitive data e.g. site names, file names, etc. are logged in full or redacted',
      ),
    tenantConfigPathPattern: z
      .string()
      .nonempty()
      .describe(
        'Path pattern to tenant configuration YAML file(s). Supports glob patterns (e.g., /app/config/*-tenant-config.yaml)',
      ),
  })
  .transform((c) => ({
    ...c,
    isDev: c.nodeEnv === 'development',
  }));

export type AppConfigFromSchema = z.infer<typeof AppConfigSchema>;

// ==========================================
// 7. Tenant Configuration
// ==========================================

export const TenantConfigSchema = z.object({
  sharepoint: SharepointConfigSchema,
  unique: UniqueConfigSchema,
  processing: ProcessingConfigSchema,
});

export type TenantConfig = z.infer<typeof TenantConfigSchema>;
