import { z } from 'zod';
import {
  coercedPositiveIntSchema,
  envResolvableRedactedStringSchema,
  urlWithoutTrailingSlashSchema,
} from '../utils/zod.util';

export const AuthMode = {
  OAUTH_2LO: 'oauth_2lo',
  PAT: 'pat',
} as const;

const oauth2loAuth = z.object({
  mode: z.literal(AuthMode.OAUTH_2LO).describe('OAuth 2.0 two-legged (client credentials)'),
  clientId: z.string().min(1),
  clientSecret: envResolvableRedactedStringSchema,
});

const patAuth = z.object({
  mode: z.literal(AuthMode.PAT).describe('Personal Access Token (Data Center only)'),
  token: envResolvableRedactedStringSchema,
});

const baseConfluenceFields = z.object({
  baseUrl: urlWithoutTrailingSlashSchema(
    'Base URL of the Confluence instance',
    'baseUrl must not end with a trailing slash',
  ),
  apiRateLimitPerMinute: coercedPositiveIntSchema.describe(
    'Number of Confluence API requests allowed per minute',
  ),
  ingestSingleLabel: z.string().describe('Label to trigger single-page sync'),
  ingestAllLabel: z.string().describe('Label to trigger full sync of all labeled pages'),
});

export const ConfluenceConfigSchema = z.discriminatedUnion('instanceType', [
  baseConfluenceFields.extend({
    instanceType: z.literal('cloud'),
    cloudId: z
      .string()
      .min(1)
      .describe(
        'Atlassian Cloud site ID — retrieve from https://<your-domain>.atlassian.net/_edge/tenant_info',
      ),
    auth: oauth2loAuth,
  }),
  baseConfluenceFields.extend({
    instanceType: z.literal('data-center'),
    auth: z.discriminatedUnion('mode', [oauth2loAuth, patAuth]),
  }),
]);

export type ConfluenceConfig = z.infer<typeof ConfluenceConfigSchema>;
