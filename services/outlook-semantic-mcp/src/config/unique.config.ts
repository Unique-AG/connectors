import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { json, stringToURL } from '~/utils/zod';

// ==== Config for local in-cluster communication with Unique API services ====

const clusterLocalConfig = z.object({
  serviceAuthMode: z
    .literal('cluster_local')
    .describe('Authentication mode to use for accessing Unique API services'),
  serviceExtraHeaders: json(z.record(z.string(), z.string()))
    .refine(
      (headers) => {
        const providedHeaders = Object.keys(headers);
        const requiredHeaders = ['x-company-id', 'x-user-id'];
        return requiredHeaders.every((header) => providedHeaders.includes(header));
      },
      {
        message: 'Must contain x-company-id and x-user-id headers',
        path: ['serviceExtraHeaders'],
      },
    )
    .describe(
      'JSON string of extra HTTP headers for API requests ' +
        '(e.g., {"x-company-id": "<company-id>", "x-user-id": "<user-id>"})',
    ),
  serviceId: z.string().describe('Service ID for auth'),
  ingestionServiceBaseUrl: z.string().describe('Base URL for Unique ingestion service'),
  scopeManagementServiceBaseUrl: z.string().describe('Base URL for Scope Management service'),
});

// ==== Config for external communication with Unique API services via app key ====

const externalConfig = z.object({
  serviceAuthMode: z
    .literal('external')
    .describe('Authentication mode to use for accessing Unique API services'),
  serviceExtraHeaders: json(z.record(z.string(), z.string()))
    .refine(
      (headers) => {
        const providedHeaders = Object.keys(headers);
        const requiredHeaders = ['authorization', 'x-app-id', 'x-user-id', 'x-company-id'];
        return requiredHeaders.every((header) => providedHeaders.includes(header));
      },
      {
        message: 'Must contain authorization, x-app-id, x-user-id, and x-company-id headers',
        path: ['serviceExtraHeaders'],
      },
    )
    .describe(
      'JSON string of extra HTTP headers for API requests ' +
        '(e.g., {"authorization": "Bearer <app-key>", "x-app-id": "<app-id>", "x-user-id": "<user-id>", "x-company-id": "<company-id>"})',
    ),
  zitadelOauthTokenUrl: z.string().describe(`Zitadel oauth token url`),
  zitadelClientId: z.string().describe(`Zitadel client id`),
  zitadelClientSecret: z.string().describe(`Zitadel client secret`),
  zitadelProjectId: z.string().describe(`Zitadel project id`),
  ingestionServiceBaseUrl: z.string().describe('Base URL for Unique ingestion service'),
  scopeManagementServiceBaseUrl: z.string().describe('Base URL for Scope Management service'),
});

// ==== Config common for both cluster_local and external authentication modes ====

const baseConfig = z.object({
  apiBaseUrl: stringToURL().describe('The Public API URL.'),
  apiVersion: z
    .string()
    .default('2023-12-06')
    .describe('The Public API version to use (maps to `x-api-version`).'),
  rootScopePath: z
    .string()
    .default('outlook-semantic-mcp')
    .describe('The root scope path where to upload transcripts.'),
  userFetchConcurrency: z.coerce
    .number()
    .int()
    .positive()
    .default(5)
    .describe('The concurrency limit for fetching users when resolving scope accesses.'),
});

export const UniqueConfigSchema = z
  .discriminatedUnion('serviceAuthMode', [clusterLocalConfig, externalConfig])
  .and(baseConfig);

export const uniqueConfig = registerConfig('unique', UniqueConfigSchema);

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
