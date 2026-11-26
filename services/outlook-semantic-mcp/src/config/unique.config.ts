import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { enabledDisabledBoolean, json } from '~/utils/zod';
import { needsUnique, UNIQUE_REQUIRED_BY, uniqueAttachmentsSchema } from './features.config';
import { mcpBackendSchema } from './mcp-backend-type.config';

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

const UniqueConnectionSchema = z
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

const envName = (field: PropertyKey | undefined): string =>
  `UNIQUE_${String(field ?? '')
    .replace(/[A-Z]/g, (letter) => `_${letter}`)
    .toUpperCase()}`;

// Disabled when no enabled feature talks to Unique: the UNIQUE_* variables are then not read.
export const UniqueConfigSchema = z
  .object({ mcpBackend: mcpBackendSchema, attachments: uniqueAttachmentsSchema })
  .catchall(z.string().optional())
  .transform((env, ctx) => {
    if (!needsUnique(env.mcpBackend, env.attachments)) {
      return { enabled: false as const };
    }
    const connection = UniqueConnectionSchema.safeParse(env);
    if (!connection.success) {
      for (const issue of connection.error.issues) {
        ctx.addIssue({
          code: 'custom',
          path: issue.path.slice(0, 1),
          message: `${envName(issue.path[0])}: ${issue.message} (Unique is needed by ${UNIQUE_REQUIRED_BY})`,
        });
      }
      return z.NEVER;
    }
    return { enabled: true as const, ...connection.data };
  });

export const uniqueConfig = registerConfig('unique', UniqueConfigSchema, {
  whitelistKeys: new Set(['MCP_BACKEND']),
});

export type UniqueConfigNamespaced = NamespacedConfigType<typeof uniqueConfig>;
export type UniqueConfig = ConfigType<typeof uniqueConfig>;
