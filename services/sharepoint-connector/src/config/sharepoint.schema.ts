import { z } from 'zod';
import { DEFAULT_GRAPH_RATE_LIMIT_PER_MINUTE_THOUSANDS } from '../constants/defaults.constants';
import { IngestionMode } from '../constants/ingestion.constants';
import { StoreInternallyMode } from '../constants/store-internally-mode.enum';
import { Redacted } from '../utils/redacted';
import {
  coercedPositiveNumberSchema,
  requiredStringSchema,
  urlWithoutTrailingSlashSchema,
} from '../utils/zod.util';

// ==========================================
// Inheritance & Permissions
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
// Auth Configuration
// ==========================================

const oidcAuthConfig = z.object({
  mode: z.literal('oidc').describe('Authentication mode to use for Microsoft APIs'),
});

const clientSecretAuthConfig = z.object({
  mode: z.literal('client-secret').describe('Authentication mode to use for Microsoft APIs'),
  clientId: requiredStringSchema.describe('Azure AD application client ID'),
  clientSecret: z
    .string()
    .nonempty()
    .transform((val) => new Redacted(val))
    .describe('Azure AD application client secret for Microsoft APIs'),
});

const certificateAuthConfig = z
  .object({
    mode: z.literal('certificate').describe('Authentication mode to use for Microsoft APIs'),
    clientId: requiredStringSchema.describe('Azure AD application client ID'),
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

export type AuthConfig = z.infer<typeof AuthConfigSchema>;

// ==========================================
// Site Configuration
// ==========================================

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

// ==========================================
// SharePoint Configuration
// ==========================================

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
      siteId: requiredStringSchema.describe('SharePoint site ID containing the configuration list'),
      listDisplayName: requiredStringSchema.describe(
        'Display name of the SharePoint configuration list',
      ),
    })
    .describe('SharePoint list details containing site configurations'),
});

const sharepointBaseConfig = z.object({
  tenantId: requiredStringSchema.describe('Azure AD tenant ID'),
  auth: AuthConfigSchema.describe('Authentication configuration for Microsoft APIs'),
  graphApiRateLimitPerMinuteThousands: coercedPositiveNumberSchema
    .prefault(DEFAULT_GRAPH_RATE_LIMIT_PER_MINUTE_THOUSANDS)
    .describe('Number of MS Graph API requests allowed per minute (in thousands)'),
  baseUrl: urlWithoutTrailingSlashSchema(
    "Your company's sharepoint URL",
    'Base URL must not end with a trailing slash',
  ),
});

export const SharepointConfigSchema = sharepointBaseConfig.and(
  z.discriminatedUnion('sitesSource', [staticSitesConfig, dynamicSitesConfig]),
);

export type StaticSitesConfig = z.infer<typeof staticSitesConfig>;
export type DynamicSitesConfig = z.infer<typeof dynamicSitesConfig>;

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
  graphApiRateLimitPerMinuteThousands: number;
  baseUrl: string;
};
