import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { redacted } from '~/utils/zod';

const ConfigSchema = z.object({
  apiBaseUrl: z
    .string()
    .prefault('https://test-api.kyckr.com/v2')
    .describe('Base URL for the Kyckr REST API. Defaults to the test environment.'),
  apiKey: redacted(z.string()).describe('Kyckr API key sent as Bearer token.'),
  mcpAccessToken: redacted(z.string())
    .optional()
    .describe(
      'Optional shared secret to protect the MCP endpoint. When set, requests must supply it as a Bearer token in the Authorization header.',
    ),
  defaultCustomerReference: z
    .string()
    .optional()
    .describe(
      'Default customer reference forwarded to Kyckr for usage reconciliation. Can be overridden per tool call.',
    ),
  defaultContactEmail: z
    .string()
    .optional()
    .describe(
      'Default contact email forwarded to Kyckr document orders. Can be overridden per tool call.',
    ),
});

export const kyckrConfig = registerConfig('kyckr', ConfigSchema);

export type KyckrConfigNamespaced = NamespacedConfigType<typeof kyckrConfig>;
export type KyckrConfig = ConfigType<typeof kyckrConfig>;
