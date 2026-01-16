import { z } from 'zod';
import {
  CRON_EVERY_15_MINUTES,
  DEFAULT_MAX_FILE_SIZE_BYTES,
  DEFAULT_PROCESSING_CONCURRENCY,
  DEFAULT_STEP_TIMEOUT_SECONDS,
} from '../constants/defaults.constants';

// ==========================================
// Processing Configuration
// ==========================================

export const ProcessingConfigSchema = z.object({
  stepTimeoutSeconds: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_STEP_TIMEOUT_SECONDS)
    .describe(
      'Sets a time limit for a file processing step before it will stop and skip processing the file',
    ),
  concurrency: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_PROCESSING_CONCURRENCY)
    .describe('Sets the concurrency of how many files you want to ingest into unique at once'),
  maxFileSizeToIngestBytes: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_MAX_FILE_SIZE_BYTES)
    .describe('Maximum file size in bytes to ingest. Files larger than this will be skipped'),
  allowedMimeTypes: z
    .union([
      z.string().transform((val) =>
        val
          ? val
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : [],
      ),
      z.array(z.string()),
    ])
    .describe('Comma-separated list or array of allowed MIME types for files to sync'),
  maxFilesToScan: z
    .preprocess(
      (val) => (val === '' ? undefined : val),
      z.coerce.number().int().positive().optional(),
    )
    .describe('For testing purpose. Maximum number of files to scan. Unlimited if not set'),
  scanIntervalCron: z
    .string()
    .default(CRON_EVERY_15_MINUTES)
    .describe('Cron expression for the scheduled file scan interval'),
});

export type ProcessingConfig = z.infer<typeof ProcessingConfigSchema>;
