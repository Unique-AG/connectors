import { z } from 'zod';
import { IngestionMode } from '../constants/ingestion.constants';
import { StoreInternallyMode } from '../constants/store-internally-mode.enum';

export const SiteConfigSchema = z.object({
  siteId: z
    .string()
    .uuidv4({
      message: 'Site ID must be a valid UUID',
    })
    .describe('SharePoint site ID for this configuration'),
  syncColumnName: z
    .string()
    .prefault('FinanceGPTKnowledge')
    .describe('Name of the SharePoint column indicating sync flag'),
  ingestionMode: z
    .enum([IngestionMode.Flat, IngestionMode.Recursive])
    .describe('Ingestion mode: flat or recursive'),
  scopeId: z.string().describe('Scope ID to be used as root for ingestion'),
  maxIngestedFiles: z
    .number()
    .int()
    .positive()
    .optional()
    .describe('Maximum number of files to ingest in a single run'),
  storeInternally: z
    .enum([StoreInternallyMode.Enabled, StoreInternallyMode.Disabled])
    .optional()
    .describe('Whether to store content internally in Unique or not'),
  syncStatus: z
    .enum(['active', 'inactive', 'deleted'])
    .default('active')
    .describe('Sync status: active, inactive, or deleted'),
  inheritMode: z
    .enum(['inherit_scopes_and_files', 'inherit_scopes', 'inherit_files', 'none'])
    .optional()
    .describe('Inheritance mode for generated scopes and ingested files'),
  syncMode: z
    .enum(['content_only', 'content_and_permissions'])
    .optional()
    .describe('Mode of synchronization from SharePoint to Unique'),
  processingMaxFilesToScan: z
    .number()
    .int()
    .positive()
    .optional()
    .describe('Maximum number of files to scan for this site'),
  processingCronInterval: z
    .string()
    .optional()
    .describe('Cron expression for scan interval for this site'),
});

export type SiteConfig = z.infer<typeof SiteConfigSchema>;

// Tenant configuration (self-contained with all required settings)
export const TenantConfigSchema = z
  .object({
    // Tenant identification
    tenantId: z.string().describe('Azure AD tenant ID'),
    clientId: z.string().describe('Azure AD application client ID'),
    clientSecret: z.string().optional().describe('Azure AD application client secret'),

    // Certificate authentication (required if authStrategy is "certificate")
    authThumbprintSha1: z
      .string()
      .optional()
      .describe('SHA1 thumbprint of the Azure AD certificate'),
    authThumbprintSha256: z
      .string()
      .optional()
      .describe('SHA256 thumbprint of the Azure AD certificate'),
    authPrivateKeyPath: z.string().optional().describe('Path to the private key file'),
    authPrivateKeyPassword: z.string().optional().describe('Password for the private key file'),

    // SharePoint configuration
    authStrategy: z
      .enum(['oidc', 'certificate', 'client-secret'])
      .describe('Authentication strategy'),
    sharepointBaseUrl: z
      .string()
      .url()
      .refine((url) => !url.endsWith('/'), {
        message: 'SharePoint base URL must not end with a trailing slash',
      })
      .describe('SharePoint base URL'),
    graphApiRateLimitPerMinute: z
      .number()
      .int()
      .positive()
      .default(780000)
      .optional()
      .describe('Microsoft Graph API rate limit per minute'),

    // Unique service configuration
    uniqueServiceAuthMode: z
      .enum(['cluster_local', 'external'])
      .default('cluster_local')
      .describe('Authentication mode for Unique services'),
    uniqueServiceExtraHeaders: z
      .record(z.string(), z.string())
      .optional()
      .describe('Extra headers for Unique services (required for cluster_local)'),
    uniqueZitadelClientId: z.string().optional().describe('Zitadel client ID'),
    uniqueZitadelClientSecret: z.string().optional().describe('Zitadel client secret'),
    uniqueZitadelProjectId: z.string().optional().describe('Zitadel project ID'),
    uniqueZitadelOauthTokenUrl: z.string().optional().describe('Zitadel OAuth token URL'),

    ingestionServiceBaseUrl: z
      .string()
      .url()
      .refine((url) => !url.endsWith('/'), {
        message: 'Ingestion service URL must not end with a trailing slash',
      })
      .describe('Unique ingestion service base URL'),
    scopeManagementServiceBaseUrl: z
      .string()
      .url()
      .refine((url) => !url.endsWith('/'), {
        message: 'Scope management service URL must not end with a trailing slash',
      })
      .describe('Unique scope management service base URL'),
    uniqueApiRateLimitPerMinute: z
      .number()
      .int()
      .positive()
      .default(100)
      .optional()
      .describe('Unique API rate limit per minute'),

    // Global defaults for sites (optional, can be overridden per site)
    ingestionMode: z
      .enum([IngestionMode.Flat, IngestionMode.Recursive])
      .optional()
      .describe('Default ingestion mode'),
    scopeId: z.string().optional().describe('Default root scope ID'),
    maxIngestedFiles: z
      .number()
      .int()
      .positive()
      .optional()
      .describe('Default max files to ingest'),
    storeInternally: z
      .enum([StoreInternallyMode.Enabled, StoreInternallyMode.Disabled])
      .optional()
      .describe('Default store internally setting'),
    inheritMode: z
      .enum(['inherit_scopes_and_files', 'inherit_scopes', 'inherit_files', 'none'])
      .optional()
      .describe('Default inheritance mode'),
    syncMode: z
      .enum(['content_only', 'content_and_permissions'])
      .optional()
      .describe('Default sync mode'),

    // Processing configuration
    processingStepTimeoutSeconds: z.number().int().positive().optional(),
    processingConcurrency: z.number().int().positive().optional(),
    processingMaxFileSizeBytes: z.number().int().positive().optional(),
    processingMaxFilesToScan: z.number().int().positive().optional(),
    processingAllowedMimeTypes: z.array(z.string()).optional(),
    processingScanIntervalCron: z.string().optional(),

    // Logging configuration
    logsDiagnosticsDataPolicy: z
      .enum(['conceal', 'disclose'])
      .default('conceal')
      .optional()
      .describe('Controls whether sensitive data e.g. site names, file names, etc. are logged in full or redacted'),

    // Configuration source settings
    sitesConfigurationSource: z
      .enum(['inline', 'sharePointList'])
      .describe(
        'Source for loading site configurations: inline (defined in this file) or sharePointList (from SharePoint list)',
      ),
    sitesConfigListUrl: z
      .string()
      .url()
      .optional()
      .describe(
        'Full SharePoint list URL for loading site configurations when using sharePointList source',
      ),
    sites: z
      .array(SiteConfigSchema)
      .optional()
      .describe('Array of site configurations ONLY USED FOR INLINE SOURCE'),
  })
  .refine(
    (data) => {
      if (data.sitesConfigurationSource === 'sharePointList') {
        return !!data.sitesConfigListUrl;
      }
      return true;
    },
    {
      message: "sitesConfigListUrl is required when sitesConfigurationSource is 'sharePointList'",
      path: ['sitesConfigListUrl'],
    },
  )
  .refine(
    (data) => {
      if (data.sitesConfigurationSource === 'inline') {
        return !!data.sites && data.sites.length > 0;
      }
      return true;
    },
    {
      message: "sites is required and must not be empty when sitesConfigurationSource is 'inline'",
      path: ['sites'],
    },
  );

export type TenantConfig = z.infer<typeof TenantConfigSchema>;
