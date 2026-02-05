import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';

export const EmailSyncConfigSchema = z.object({
  syncIntervalCron: z
    .string()
    .default('0 */15 * * * *')
    .describe('Cron expression for email sync interval (default: every 15 minutes)'),
  batchSize: z.coerce
    .number()
    .int()
    .positive()
    .default(200)
    .describe('Number of messages to fetch per API request'),
  enabled: z.coerce
    .boolean()
    .default(true)
    .describe('Whether email sync scheduler is enabled'),
});

export const emailSyncConfig = registerConfig('emailSync', EmailSyncConfigSchema);

export type EmailSyncConfigNamespaced = NamespacedConfigType<typeof emailSyncConfig>;
export type EmailSyncConfig = ConfigType<typeof emailSyncConfig>;
