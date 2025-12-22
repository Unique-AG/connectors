import { z } from 'zod';
import {
  CRON_EVERY_15_MINUTES,
  DEFAULT_MAX_FILE_SIZE_BYTES,
  DEFAULT_PROCESSING_CONCURRENCY,
  DEFAULT_STEP_TIMEOUT_SECONDS,
  DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE,
} from '../constants/defaults.constants';
import { IngestionMode } from '../constants/ingestion.constants';
import { StoreInternallyMode } from '../constants/store-internally-mode.enum';
import { parseJsonEnvironmentVariable } from '../utils/config.util';
import { INHERITANCE_MODES } from '../utils/inheritance.util';
import { Redacted } from '../utils/redacted';

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
  scopeId: z
  .string()
  .describe('Scope ID to be used as root for ingestion'),
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
    .enum(INHERITANCE_MODES)
    .optional()
    .describe('This config has effect only in content_only sync mode. It indicates whether we should inherit permissions for newly created scopes and files in Unique Knowledge Base. Allowed values: none, inherit_scopes, inherit_files, inherit_scopes_and_files'),
  syncMode: z
    .enum(['content_only', 'content_and_permissions'])
    .describe(
      'Mode of synchronization from SharePoint to Unique. ' +
        'content_only: sync only the content, ' +
        'content_and_permissions: sync both content and permissions',
    ),
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
    serviceAuthMode: z
      .enum(['cluster_local', 'external'])
      .default('cluster_local')
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
      .optional()
      .describe(
        'JSON string of extra HTTP headers for ingestion API requests ' +
          '(e.g., {"x-company-id": "<company-id>", "x-user-id": "<user-id>"})',
      ),
    zitadelOauthTokenUrl: z.url().optional().describe('Zitadel login token'),
    zitadelProjectId: z.string().optional().describe('Zitadel project ID'),
    zitadelClientId: z.string().optional().describe('Zitadel client ID'),
    zitadelClientSecret: z
      .string()
      .transform((val) => new Redacted(val))
      .optional()
      .describe('Zitadel client secret'),

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
    uniqueApiRateLimitPerMinute: z.coerce
      .number()
      .int()
      .positive()
      .default(DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE)
      .describe('Number of Unique API requests allowed per minute'),

    // Processing configuration
    processingStepTimeoutSeconds: z.coerce
      .number()
      .int()
      .positive()
      .default(DEFAULT_STEP_TIMEOUT_SECONDS)
      .describe(
        'Sets a time limit for a file processing step before it will stop and skip processing the file',
      ),
    processingConcurrency: z.coerce
      .number()
      .int()
      .positive()
      .default(DEFAULT_PROCESSING_CONCURRENCY)
      .describe('Sets the concurrency of how many files you want to ingest into unique at once'),
    processingMaxFileSizeBytes: z.coerce
      .number()
      .int()
      .positive()
      .default(DEFAULT_MAX_FILE_SIZE_BYTES)
      .describe(
        'Sets the maximum file size in bytes that we are ingesting. Anything above this value will be skipped',
      ),
    processingAllowedMimeTypes: z
      .string()
      .transform((val) =>
        val
          ? val
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : [],
      )
      .describe('Comma-separated list of allowed MIME types for files to sync'),
    processingMaxFilesToScan: z
      .preprocess(
        (val) => (val === '' ? undefined : val),
        z.coerce.number().int().positive().optional(),
      )
      .describe('For testing purpose. Maximum number of files to scan. Unlimited if not set'),
    processingScanIntervalCron: z
      .string()
      .default(CRON_EVERY_15_MINUTES)
      .describe('Cron expression for the scheduled file scan interval'),

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
  )
  .refine(
    (data) => {
      if (data.serviceAuthMode === 'cluster_local') {
        return !!data.serviceExtraHeaders;
      }
      return true;
    },
    {
      message: "serviceExtraHeaders is required when serviceAuthMode is 'cluster_local'",
      path: ['serviceExtraHeaders'],
    },
  )
  .refine(
    (data) => {
      if (data.serviceAuthMode === 'external') {
        return !!(
          data.zitadelOauthTokenUrl &&
          data.zitadelProjectId &&
          data.zitadelClientId &&
          data.zitadelClientSecret
        );
      }
      return true;
    },
    {
      message:
        "zitadelOauthTokenUrl, zitadelProjectId, zitadelClientId, and zitadelClientSecret are required when serviceAuthMode is 'external'",
      path: ['serviceAuthMode'],
    },
  );

export type TenantConfig = z.infer<typeof TenantConfigSchema>;
