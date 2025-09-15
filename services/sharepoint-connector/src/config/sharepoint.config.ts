import { env } from 'node:process';
import { registerAs } from '@nestjs/config';
import { z } from 'zod';

const namespace = 'sharepoint' as const;

export const EnvironmentVariables = z.object({
  GRAPH_CLIENT_ID: z.string().min(1).describe('Azure AD application client ID for Microsoft Graph'),
  GRAPH_CLIENT_SECRET: z
    .string()
    .min(1)
    .describe('Azure AD application client secret for Microsoft Graph'),
  GRAPH_TENANT_ID: z.string().min(1).describe('Azure AD tenant ID'),
  GRAPH_API_URL: z
    .string()
    .default('https://graph.microsoft.com')
    .describe('Microsoft Graph API base URL'),
  SHAREPOINT_SITES: z
    .string()
    .default('')
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
    .min(1)
    .default('FinanceGPTKnowledge')
    .describe('Name of the SharePoint column indicating sync flag'),
  ALLOWED_MIME_TYPES: z
    .string()
    .default('')
    .transform((val) =>
      val
        ? val
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
        : [],
    )
    .describe('Comma-separated list of allowed MIME types for files to sync'),
});

export interface Config {
  [namespace]: {
    clientId: string;
    clientSecret: string;
    tenantId: string;
    apiUrl: string;
    sites: string[];
    syncColumnName: string;
    allowedMimeTypes: string[];
  };
}

export const sharepointConfig = registerAs<Config[typeof namespace]>(namespace, () => {
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
  } satisfies Config[typeof namespace];
});

export type SharepointConfig = typeof sharepointConfig;
