import { env } from 'node:process';
import { registerAs } from '@nestjs/config';
import { z } from 'zod';

const namespace = 'sharepoint' as const;

const EnvironmentVariables = z
  .object({
    GRAPH_CLIENT_ID: z
      .string()
      .min(1)
      .optional()
      .describe('Azure AD application client ID for Microsoft Graph (optional when using OIDC)'),
    GRAPH_CLIENT_SECRET: z
      .string()
      .optional()
      .describe(
        'Azure AD application client secret for Microsoft Graph (not required when using OIDC)',
      ),
    GRAPH_TENANT_ID: z.string().min(1).describe('Azure AD tenant ID'),
    GRAPH_API_URL: z
      .string()
      .prefault('https://graph.microsoft.com')
      .describe('Microsoft Graph API base URL'),
    SHAREPOINT_SITES: z
      .string()
      .prefault('')
      .transform((val) =>
        val
          ? val
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : [],
      )
      .describe('Comma-separated list of SharePoint site IDs to scan'),
    SHAREPOINT_SYNC_COLUMN_NAME: z
      .string()
      .prefault('FinanceGPTKnowledge')
      .describe('Name of the SharePoint column indicating sync flag'),
    ALLOWED_MIME_TYPES: z
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
    SHAREPOINT_MAX_FILES_TO_SCAN: z.coerce
      .number()
      .int()
      .positive()
      .optional()
      .describe('For testing purpose. Maximum number of files to scan. Unlimited if not set'),
    GRAPH_USE_OIDC_AUTH: z.coerce
      .boolean()
      .default(false)
      .describe('Use OIDC/Workload Identity authentication instead of client secret'),
  })
  .refine(
    (data) => {
      // When not using OIDC, client credentials are required
      if (!data.GRAPH_USE_OIDC_AUTH) {
        return data.GRAPH_CLIENT_ID && data.GRAPH_CLIENT_SECRET;
      }
      // When using OIDC, only tenant ID is required
      return true;
    },
    {
      message:
        'GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET are required when GRAPH_USE_OIDC_AUTH is false',
    },
  );

export interface SharepointConfig {
  [namespace]: {
    clientId?: string;
    clientSecret?: string;
    tenantId: string;
    apiUrl: string;
    sites: string[];
    syncColumnName: string;
    allowedMimeTypes: string[];
    maxFilesToScan?: number;
    useOidc: boolean;
  };
}

export const sharepointConfig = registerAs<SharepointConfig[typeof namespace]>(namespace, () => {
  const validEnv = EnvironmentVariables.safeParse(env);
  if (!validEnv.success) {
    throw new TypeError(`Invalid config for namespace "${namespace}": ${validEnv.error.message}`);
  }
  return {
    clientId: validEnv.data.GRAPH_CLIENT_ID,
    clientSecret: validEnv.data.GRAPH_CLIENT_SECRET,
    tenantId: validEnv.data.GRAPH_TENANT_ID,
    apiUrl: validEnv.data.GRAPH_API_URL,
    sites: validEnv.data.SHAREPOINT_SITES,
    syncColumnName: validEnv.data.SHAREPOINT_SYNC_COLUMN_NAME,
    allowedMimeTypes: validEnv.data.ALLOWED_MIME_TYPES,
    maxFilesToScan: validEnv.data.SHAREPOINT_MAX_FILES_TO_SCAN,
    useOidc: validEnv.data.GRAPH_USE_OIDC_AUTH,
  };
});
