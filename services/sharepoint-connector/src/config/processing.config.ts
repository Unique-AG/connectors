import { ConfigType } from '@nestjs/config';
import { NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import {
  CRON_EVERY_15_MINUTES,
  DEFAULT_MAX_FILE_SIZE_BYTES,
  DEFAULT_PROCESSING_CONCURRENCY,
  DEFAULT_STEP_TIMEOUT_SECONDS,
} from '../constants/defaults.constants';

const ProcessingConfigSchema = z.object({
  syncMode: z
    .enum(['content-only', 'content-and-permissions'])
    .default('content-only')
    .describe('Mode of synchronization from SharePoint to Unique'),
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
  maxFileSizeBytes: z.coerce
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_MAX_FILE_SIZE_BYTES)
    .describe(
      'Sets the maximum file size in bytes that we are ingesting. Anything above this value will be skipped',
    ),
  allowedMimeTypes: z
    .string()
    .transform((val) =>
      val
        ? val
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
        : [],
    )
    .describe('Comma-separated list of allowed MIME types for files to sync'),
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

export const processingConfig = registerConfig('processing', ProcessingConfigSchema);

export type ProcessingConfigNamespaced = NamespacedConfigType<typeof processingConfig>;
export type ProcessingConfig = ConfigType<typeof processingConfig>;
