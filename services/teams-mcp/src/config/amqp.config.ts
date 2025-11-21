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
      .refine((u) => u.protocol === 'amqp:', 'The supplied URL must be using `amqp:` protocol'),
  ).describe('The AMQP connection url.'),
});

export const amqpConfig = registerConfig('amqp', ConfigSchema);

export type AMQPConfigNamespaced = NamespacedConfigType<typeof amqpConfig>;
export type AMQPConfig = ConfigType<typeof amqpConfig>;
