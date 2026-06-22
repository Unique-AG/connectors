import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { redacted } from '~/utils/zod';

const ConfigSchema = z.object({
  apiBaseUrl: z
    .string()
    .prefault('https://api.temenos.com/api/v1.0.0')
    .describe('Base URL for the Temenos DataHub REST API.'),
  apiKey: redacted(z.string()).describe('Temenos API key sent as the `apikey` header.'),
});

export const temenosConfig = registerConfig('temenos', ConfigSchema);

export type TemenosConfigNamespaced = NamespacedConfigType<typeof temenosConfig>;
export type TemenosConfig = ConfigType<typeof temenosConfig>;
