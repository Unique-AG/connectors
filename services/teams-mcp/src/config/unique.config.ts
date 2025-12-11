import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { json, redacted, stringToURL } from '~/utils/zod';

// ==== Config for local in-cluster communication with Unique API services ====

const clusterLocalConfig = z.object({
  serviceAuthMode: z
    .literal('cluster_local')
    .describe('Authentication mode to use for accessing Unique API services'),
  serviceExtraHeaders: json(z.record(z.string(), z.string()))
    .refine(
      (headers) => {
        const providedHeaders = Object.keys(headers);
        const requiredHeaders = ['x-company-id', 'x-user-id', 'x-service-id'];
        return requiredHeaders.every((header) => providedHeaders.includes(header));
      },
      {
        message: 'Must contain x-company-id, x-user-id, and x-service-id headers',
        path: ['serviceExtraHeaders'],
      },
    )
    .describe(
      'JSON string of extra HTTP headers for API requests ' +
        '(e.g., {"x-company-id": "<company-id>", "x-user-id": "<user-id>", "x-service-id": "<service-id>"})',
    ),
  ingestionServiceBaseUrl: stringToURL().describe('Base URL for Unique ingestion service'),
});

// ==== Config for external communication with Unique API services via app key ====

const externalConfig = z.object({
  serviceAuthMode: z
    .literal('external')
    .describe('Authentication mode to use for accessing Unique API services'),
  appKey: redacted(z.string()).describe('API key of a Chat App (maps to `Authorization`).'),
  appId: z.string().describe('App ID of the Chat App (maps to `x-app-id`).'),
  authUserId: z.string().describe('User ID of a Zitadel Service User (maps to `x-user-id`).'),
  authCompanyId: z
    .string()
    .describe(
      'Organisation ID of where the Zitadel Service User is created (maps to `x-company-id`).',
    ),
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
    .default('Teams-MCP')
    .describe('The root scope path where to upload recordings and transcripts.'),
});

export const UniqueConfigSchema = z
  .discriminatedUnion('serviceAuthMode', [clusterLocalConfig, externalConfig])
  .and(baseConfig);

export const uniqueConfig = registerConfig('unique', UniqueConfigSchema);

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
