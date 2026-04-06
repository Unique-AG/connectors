import { z } from 'zod';
import {
  CRON_EVERY_15_MINUTES,
  DEFAULT_PROCESSING_CONCURRENCY,
} from '../constants/defaults.constants';
import { coercedPositiveIntSchema } from '../utils/zod.util';

export const ProcessingConfigSchema = z.object({
  concurrency: coercedPositiveIntSchema
    .prefault(DEFAULT_PROCESSING_CONCURRENCY)
    .describe('Sets the concurrency of how many pages you want to ingest into unique at once'),
  scanIntervalCron: z
    .string()
    .prefault(CRON_EVERY_15_MINUTES)
    .describe('Cron expression for the scheduled page scan interval'),
  maxItemsToScan: z
    .preprocess(
      (val) => (val === '' ? undefined : val),
      z.coerce.number().int().positive().optional(),
    )
    .describe(
      'For testing purpose. Maximum number of items (pages + attachments) to scan. Unlimited if not set',
    ),
});

export type ProcessingConfig = z.infer<typeof ProcessingConfigSchema>;
