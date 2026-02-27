import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { enabledDisabledBoolean, json } from '~/utils/zod';

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
});

// ==== Config for external communication with Unique API services via app key ====

const externalConfig = z.object({
  serviceAuthMode: z
    .literal('external')
    .describe('Authentication mode to use for accessing Unique API services'),
  zitadelOauthTokenUrl: z.string().describe(`Zitadel oauth token url`),
  zitadelClientId: z.string().describe(`Zitadel client id`),
  zitadelClientSecret: z.string().describe(`Zitadel client secret`),
  zitadelProjectId: z.string().describe(`Zitadel project id`),
});

// ==== Config common for both cluster_local and external authentication modes ====

export const UniqueConfigSchema = z
  .discriminatedUnion('serviceAuthMode', [clusterLocalConfig, externalConfig])
  .and(
    z.object({
      ingestionServiceBaseUrl: z.string().describe('Base URL for Unique ingestion service'),
      scopeManagementServiceBaseUrl: z.string().describe('Base URL for Scope Management service'),
      storeInternally: enabledDisabledBoolean(
        'Whether to store content internally in Unique or not.',
      ),
    }),
  );

export const uniqueConfig = registerConfig('unique', UniqueConfigSchema);

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
