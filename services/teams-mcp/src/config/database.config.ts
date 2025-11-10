import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { redacted } from '~/utils/zod';

const ConfigSchema = z.object({
  url: redacted(
    z
      .url()
      .transform((v) => new URL(v))
      .refine(
        (u) => u.protocol === 'postgresql:',
        'The supplied URL must be using `postgresql:` protocol',
      )
      .describe('The postgres connection URL'),
  ),
});

export const databaseConfig = registerConfig('database', ConfigSchema);

export type DatabaseConfigNamespaced = NamespacedConfigType<typeof databaseConfig>;
export type DatabaseConfig = ConfigType<typeof databaseConfig>;
