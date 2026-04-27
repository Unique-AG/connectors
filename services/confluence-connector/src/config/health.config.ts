import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import {
  DEFAULT_HEALTH_CONNECTIVITY_TIMEOUT_MS,
  DEFAULT_HEALTH_SYNC_HISTORY_SIZE,
  DEFAULT_HEALTH_SYNC_TENANT_FAILURE_THRESHOLD,
} from '../constants/defaults.constants';
import { coercedPositiveIntSchema } from '../utils/zod.util';

export const HealthConfigSchema = z.object({
  syncHistorySize: coercedPositiveIntSchema
    .prefault(DEFAULT_HEALTH_SYNC_HISTORY_SIZE)
    .describe(
      'Number of recent sync runs kept per tenant in the sliding window for health checks',
    ),
  syncTenantFailureThreshold: z.coerce
    .number()
    .min(0)
    .max(1)
    .prefault(DEFAULT_HEALTH_SYNC_TENANT_FAILURE_THRESHOLD)
    .describe(
      'Per-tenant failure ratio (0-1) across the window that marks the service unhealthy when exceeded',
    ),
  connectivityTimeoutMs: coercedPositiveIntSchema
    .prefault(DEFAULT_HEALTH_CONNECTIVITY_TIMEOUT_MS)
    .describe(
      'Timeout in milliseconds for each unauthenticated reachability ping used in health checks',
    ),
});

export const healthConfig = registerConfig('health', HealthConfigSchema);

export type HealthConfig = ConfigType<typeof healthConfig>;
export type HealthConfigNamespaced = NamespacedConfigType<typeof healthConfig>;
