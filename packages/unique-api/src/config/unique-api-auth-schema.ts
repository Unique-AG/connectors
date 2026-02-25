import { z } from 'zod/v4';

// ==== Config for local in-cluster communication with Unique API services ====
const authClusterLocalConfig = z.object({
  serviceAuthMode: z
    .literal('cluster_local')
    .describe('Authentication mode to use for accessing Unique API services'),
  serviceExtraHeaders: z
    .record(z.string(), z.string())
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
const authExternalConfig = z.object({
  serviceAuthMode: z
    .literal('external')
    .describe('Authentication mode to use for accessing Unique API services'),
  zitadelOauthTokenUrl: z.string().describe(`Zitadel oauth token url`),
  zitadelClientId: z.string().describe(`Zitadel client id`),
  zitadelClientSecret: z.string().describe(`Zitadel client secret`),
  zitadelProjectId: z.string().describe(`Zitadel project id`),
});
// ==== Config common for both cluster_local and external authentication modes ====

export const UniqueAuthSchema = z.discriminatedUnion('serviceAuthMode', [
  authClusterLocalConfig,
  authExternalConfig,
]);

export type UniqueAuthExternalConfig = z.infer<typeof authExternalConfig>;

export type UniqueAuthConfig = z.infer<typeof UniqueAuthSchema>;
