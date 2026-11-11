import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { redacted, stringToURL } from '~/utils/zod';

const ConfigSchema = z.object({
  clientId: z
    .string()
    .min(1)
    .describe('The client ID of the Microsoft App Registration that the MCP Server will use.'),
  clientSecret: redacted(z.string().min(1)).describe(
    'The client secret of the Microsoft App Registration that the MCP Server will use.',
  ),
  signInTenantId: z
    .string()
    .min(1)
    .prefault('common')
    .describe(
      'Sign-in tenant ID the OAuth login should open. Set a GUID when sign-in must use the Enterprise Application (service principal) in a foreign tenant. Leave as "common" when users choose their directory at login. Independent of clientId/clientSecret; not the tenant that owns the app registration.',
    ),
  adminConsentRedirectUri: z
    .url({ protocol: /^https?$/ })
    .prefault('https://www.unique.ai/setup/consent-completed/entra-id')
    .describe(
      'Where Microsoft Entra sends a tenant admin after they grant admin consent through /admin/consent. Must be registered as a redirect URI on the app registration. The default matches the admin_consent_redirect_uri default of the Terraform module.',
    ),
  webhookSecret: redacted(z.string().length(128)).describe(
    'The webhook secret for validating subscriptions hooks (spoof protection). Must be a 128 random characters.',
  ),
  publicWebhookUrl: stringToURL()
    .prefault(process.env.SELF_URL ?? '')
    .describe(
      'The public webhook URL reachable from external network used by Microsoft Graph subscription for pushes. Optional - defaults to SELF_URL environment variable if not provided.',
    ),
  subscriptionExpirationTimeHoursUTC: z.coerce
    .number<string | undefined>()
    .min(0)
    .max(23)
    .default(3)
    .describe(
      'The hour of the day in UTC when scheduled subscription expirations should occur. This should be done during off-peak hours to avoid disruptions of incoming notifications.',
    ),
  allowedTenantIds: z
    .string()
    .optional()
    .transform((val) =>
      (val ?? '')
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean),
    )
    .pipe(z.array(z.guid()))
    .describe(
      'Comma-separated list of Entra tenant GUIDs allowed to use the MCP server (MICROSOFT_ALLOWED_TENANT_IDS). When set, sign-ins from unlisted tenants are rejected, and a user whose tenant is removed loses access at their next Microsoft token refresh. Leave unset to allow any tenant.',
    ),
});

export const microsoftConfig = registerConfig('microsoft', ConfigSchema);

export type MicrosoftConfigNamespaced = NamespacedConfigType<typeof microsoftConfig>;
export type MicrosoftConfig = ConfigType<typeof microsoftConfig>;
