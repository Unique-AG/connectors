import { ConfigType } from '@nestjs/config';
import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { DEFAULT_GRAPH_RATE_LIMIT_PER_10_SECONDS } from '../constants/defaults.constants';
import { Redacted } from '../utils/redacted';

const SharepointConfig = z
  .object({
    // We do not use standard boolean coercion because any non-empty string is true, while we would
    // like any string different from "true" to be false
    graphUseOidcAuth: z
      .string()
      .transform((val) => val.toLowerCase() === 'true')
      .default(false)
      .describe('Use OIDC/Workload Identity authentication instead of client secret'),
    graphClientId: z
      .string()
      .min(1)
      .optional()
      .describe('Azure AD application client ID for Microsoft Graph (optional when using OIDC)'),
    graphClientSecret: z
      .string()
      .optional()
      .transform((val) => (val ? new Redacted(val) : undefined))
      .describe(
        'Azure AD application client secret for Microsoft Graph (not required when using OIDC)',
      ),
    graphTenantId: z.string().min(1).describe('Azure AD tenant ID'),
    graphApiUrl: z
      .url()
      .prefault('https://graph.microsoft.com')
      .describe('Microsoft Graph API base URL'),
    graphRateLimitPer10Seconds: z.coerce
      .number()
      .int()
      .positive()
      .prefault(DEFAULT_GRAPH_RATE_LIMIT_PER_10_SECONDS)
      .describe('Number of MS Graph API requests allowed per 10 seconds'),
    baseUrl: z.url().describe("Your company's sharepoint URL"),
    siteIds: z
      .string()
      .prefault('')
      .transform((val) =>
        val
          ? val
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : [],
      )
      .describe('Comma-separated list of SharePoint site IDs to scan'),
    syncColumnName: z
      .string()
      .prefault('FinanceGPTKnowledge')
      .describe('Name of the SharePoint column indicating sync flag'),
  })
  .refine(
    (config) => {
      // When not using OIDC, client credentials are required
      if (!config.graphUseOidcAuth) {
        return config.graphClientId && config.graphClientSecret;
      }
      // When using OIDC, only tenant ID is required
      return true;
    },
    {
      message:
        'GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET are required when GRAPH_USE_OIDC_AUTH is false',
    },
  );

export const sharepointConfig = registerConfig('sharepoint', SharepointConfig);

export type SharepointConfigNamespaced = NamespacedConfigType<typeof sharepointConfig>;
export type SharepointConfig = ConfigType<typeof sharepointConfig>;
