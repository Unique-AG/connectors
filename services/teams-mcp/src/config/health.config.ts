import { type ConfigType, type NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';

const ConfigSchema = z.object({
  connectivityTimeoutMs: z.coerce
    .number()
    .int()
    .prefault(3000)
    .describe('Timeout (ms) for the unauthenticated MS Graph connectivity ping.'),
  amqpCheckTimeoutMs: z.coerce
    .number()
    .int()
    .prefault(5000)
    .describe('Timeout (ms) for the RabbitMQ exchange check.'),
  subscriptionExpiredThreshold: z.coerce
    .number()
    .min(0)
    .max(1)
    .prefault(0.15)
    .describe(
      'Ratio of expired transcript subscriptions (expired ÷ total) above which the subscription health indicator reports `down`.',
    ),
});

export const healthConfig = registerConfig('health', ConfigSchema);

export type HealthConfigNamespaced = NamespacedConfigType<typeof healthConfig>;
export type HealthConfig = ConfigType<typeof healthConfig>;
