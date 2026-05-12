import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';

const HealthConfigSchema = z.object({
  connectivityTimeoutMs: z.coerce
    .number()
    .int()
    .positive()
    .prefault(3000)
    .describe('Timeout in milliseconds for connectivity health checks.'),
  connectorFailureThreshold: z.coerce
    .number()
    .min(0)
    .max(1)
    .prefault(0.15)
    .describe('Fraction of eligible users that may be failing before the connector is marked down.'),
  delegatedAccessStalenessThresholdHours: z.coerce
    .number()
    .int()
    .positive()
    .prefault(24)
    .describe('Hours after which a delegated access account is considered stale.'),
});

export const healthConfig = registerConfig('health', HealthConfigSchema);

export type HealthConfigNamespaced = NamespacedConfigType<typeof healthConfig>;
export type HealthConfig = ConfigType<typeof healthConfig>;
