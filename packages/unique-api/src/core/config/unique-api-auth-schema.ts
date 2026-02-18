import { z } from 'zod/v4';

// ==== Config for local in-cluster communication with Unique API services ====
const authClusterLocalConfig = z.object({
  mode: z
    .literal('cluster_local')
    .describe('Authentication mode to use for accessing Unique API services'),
  extraHeaders: z
    .record(z.string(), z.string())
    .refine(
      (headers) => {
        const providedHeaders = Object.keys(headers);
        const requiredHeaders = ['x-company-id', 'x-user-id'];
        return requiredHeaders.every((header) => providedHeaders.includes(header));
      },
      {
        message: 'Must contain x-company-id and x-user-id headers',
        path: ['extraHeaders'],
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
  mode: z
    .literal('external')
    .describe('Authentication mode to use for accessing Unique API services'),
  zitadelOauthTokenUrl: z.string().describe(`Zitadel oauth token url`),
  zitadelClientId: z.string().describe(`Zitadel client id`),
  zitadelClientSecret: z.string().describe(`Zitadel client secret`),
  zitadelProjectId: z.string().describe(`Zitadel project id`),
});
// ==== Config common for both cluster_local and external authentication modes ====

export const UniqueAuthSchema = z.discriminatedUnion('mode', [
  authClusterLocalConfig,
  authExternalConfig,
]);

export type UniqueAuthConfig = z.infer<typeof UniqueAuthSchema>;
