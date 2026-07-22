import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { json, stringToURL } from '~/utils/zod';

const serviceExtraHeadersClusterLocal = json(z.record(z.string(), z.string()))
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
  );

const serviceExtraHeadersExternal = json(z.record(z.string(), z.string()))
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
  );

const enabledCommonFields = {
  integration: z
    .literal('enabled')
    .describe(
      'Unique integration is enabled; knowledge base tools and ingestion require full Unique config.',
    ),
  apiBaseUrl: stringToURL().describe('The Public API URL.'),
  apiVersion: z
    .string()
    .default('2023-12-06')
    .describe('The Public API version to use (maps to `x-api-version`).'),
  rootScopeId: z
    .string()
    .min(1, 'rootScopeId cannot be empty')
    .describe('The root scope ID under which to create transcript and recording folders.'),
  userFetchConcurrency: z.coerce
    .number()
    .int()
    .positive()
    .default(5)
    .describe('The concurrency limit for fetching users when resolving scope accesses.'),
};

const enabledClusterLocalConfig = z.object({
  ...enabledCommonFields,
  serviceAuthMode: z
    .literal('cluster_local')
    .describe('Authentication mode to use for accessing Unique API services'),
  serviceExtraHeaders: serviceExtraHeadersClusterLocal,
  ingestionServiceBaseUrl: stringToURL().describe('Base URL for Unique ingestion service'),
});

const enabledExternalConfig = z.object({
  ...enabledCommonFields,
  serviceAuthMode: z
    .literal('external')
    .describe('Authentication mode to use for accessing Unique API services'),
  serviceExtraHeaders: serviceExtraHeadersExternal,
});

const disabledUniqueConfig = z.object({
  integration: z
    .literal('disabled')
    .describe('Unique integration is disabled; chat-only mode without knowledge base features.'),
});

// Enabled variants are separate object schemas (Zod 4 discriminatedUnion does not support `.and()`).
export const UniqueConfigSchema = z.union([
  disabledUniqueConfig,
  z.discriminatedUnion('serviceAuthMode', [enabledClusterLocalConfig, enabledExternalConfig]),
]);

export const uniqueConfig = registerConfig('unique', UniqueConfigSchema);

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
export type EnabledUniqueConfig = Extract<UniqueConfig, { integration: 'enabled' }>;
export type DisabledUniqueConfig = Extract<UniqueConfig, { integration: 'disabled' }>;
