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
  syncColumnName: z.string().describe('Name of the SharePoint column indicating sync flag'),
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
export const TenantConfigSchema = z.object({
  // Tenant identification
  tenantId: z.string().describe('Azure AD tenant ID'),
  clientId: z.string().describe('Azure AD application client ID'),

  // SharePoint configuration
  authStrategy: z
    .enum(['oidc', 'certificate', 'client-secret'])
    .describe('Authentication strategy'),
  sharepointBaseUrl: z
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
  ingestionServiceBaseUrl: z
    .url()
    .refine((url) => !url.endsWith('/'), {
      message: 'Ingestion service URL must not end with a trailing slash',
    })
    .describe('Unique ingestion service base URL'),
  scopeManagementServiceBaseUrl: z
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

  // Configuration source settings
  sitesConfigurationSource: z
    .enum(['inline', 'sharePointList'])
    .describe(
      'Source for loading site configurations: inline (defined in this file) or sharePointList (from SharePoint list)',
    ),
  sitesConfigListUrl: z
    .string()
    .optional()
    .describe(
      'Full SharePoint list URL for loading site configurations when using sharePointList source',
    ),
  sitesConfig: z
    .array(SiteConfigSchema)
    .optional()
    .describe('Array of site configurations ONLY USED FOR INLINE SOURCE'),
});

export type TenantConfig = z.infer<typeof TenantConfigSchema>;
