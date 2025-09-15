import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';

const ConfigSchema = z.object({
  version: z
    .string()
    .default('unset')
    .describe('Current version tagged during deployments for the running service'),
  maxHeapMb: z
    .number()
    .int()
    .describe(
      'Maximum heap memory allocation in megabytes before triggering health warnings or corrective actions',
    ),
});

export const healthConfig = registerConfig('health', ConfigSchema, {
  whitelistKeys: new Set(['MAX_HEAP_MB', 'VERSION']),
});

export type HealthConfigNamespaced = NamespacedConfigType<typeof healthConfig>;
export type HealthConfig = ConfigType<typeof healthConfig>;
