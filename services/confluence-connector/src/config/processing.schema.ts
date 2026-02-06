import { z } from 'zod';
import {
  CRON_EVERY_15_MINUTES,
  DEFAULT_PROCESSING_CONCURRENCY,
  DEFAULT_STEP_TIMEOUT_SECONDS,
} from '../constants/defaults.constants';
import { coercedPositiveIntSchema } from '../utils/zod.util';

export const ProcessingConfigSchema = z.object({
  stepTimeoutSeconds: coercedPositiveIntSchema
    .prefault(DEFAULT_STEP_TIMEOUT_SECONDS)
    .describe('Sets a time limit for a page processing step before it will stop and skip processing the page'),
  concurrency: coercedPositiveIntSchema
    .prefault(DEFAULT_PROCESSING_CONCURRENCY)
    .describe('Sets the concurrency of how many pages you want to ingest into unique at once'),
  scanIntervalCron: z
    .string()
    .default(CRON_EVERY_15_MINUTES)
    .describe('Cron expression for the scheduled page scan interval'),
  maxPagesToScan: z
    .preprocess(
      (val) => (val === '' ? undefined : val),
      z.coerce.number().int().positive().optional(),
    )
    .describe('For testing purpose. Maximum number of pages to scan. Unlimited if not set'),
});

export type ProcessingConfig = z.infer<typeof ProcessingConfigSchema>;
