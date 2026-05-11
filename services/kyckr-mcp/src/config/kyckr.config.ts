import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { redacted } from '~/utils/zod';

const ConfigSchema = z.object({
  apiBaseUrl: z
    .string()
    .prefault('https://test-api.kyckr.com/v2')
    .describe('Base URL for the Kyckr REST API. Defaults to the test environment.'),
  apiKey: redacted(z.string()).describe('Kyckr API key sent as Bearer token.'),
  defaultCustomerReference: z
    .string()
    .optional()
    .describe(
      'Optional customer reference forwarded to Kyckr for usage reconciliation on paid calls.',
    ),
  defaultContactEmail: z
    .string()
    .optional()
    .describe('Optional contact email forwarded to Kyckr for document orders that need follow-up.'),
});

export const kyckrConfig = registerConfig('kyckr', ConfigSchema);

export type KyckrConfigNamespaced = NamespacedConfigType<typeof kyckrConfig>;
export type KyckrConfig = ConfigType<typeof kyckrConfig>;
