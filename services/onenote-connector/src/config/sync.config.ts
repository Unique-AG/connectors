import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';

const ConfigSchema = z.object({
  intervalCron: z
    .string()
    .default('*/15 * * * *')
    .describe('Cron expression for the sync interval. Default: every 15 minutes.'),
  concurrency: z.coerce
    .number()
    .int()
    .positive()
    .default(3)
    .describe('Max number of users to sync in parallel.'),
  pageBatchSize: z.coerce
    .number()
    .int()
    .positive()
    .default(20)
    .describe('Number of pages to process per batch during sync.'),
});

export const syncConfig = registerConfig('sync', ConfigSchema);

export type SyncConfigNamespaced = NamespacedConfigType<typeof syncConfig>;
export type SyncConfig = ConfigType<typeof syncConfig>;
