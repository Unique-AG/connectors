import { z } from 'zod';
import {
  CRON_EVERY_15_MINUTES,
  DEFAULT_MAX_FILE_SIZE_BYTES,
  DEFAULT_PROCESSING_CONCURRENCY,
  DEFAULT_STEP_TIMEOUT_SECONDS,
} from '../constants/defaults.constants';
import { coercedPositiveIntSchema } from '../utils/zod.util';

// ==========================================
// Processing Configuration
// ==========================================

export const ProcessingConfigSchema = z.object({
  stepTimeoutSeconds: coercedPositiveIntSchema
    .prefault(DEFAULT_STEP_TIMEOUT_SECONDS)
    .describe(
      'Sets a time limit for a file processing step before it will stop and skip processing the file',
    ),
  concurrency: coercedPositiveIntSchema
    .prefault(DEFAULT_PROCESSING_CONCURRENCY)
    .describe('Sets the concurrency of how many files you want to ingest into unique at once'),
  maxFileSizeToIngestBytes: coercedPositiveIntSchema
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
    .describe(
      'For testing purposes. Limit the number of files scanned. Limit is per site in case ' +
        'of subsite scan and is applied separately to files and site pages Unlimited if not set',
    ),
  scanIntervalCron: z
    .string()
    .default(CRON_EVERY_15_MINUTES)
    .describe('Cron expression for the scheduled file scan interval'),
  mimeTypeOverridesByExtension: z
    .record(z.string(), z.string().min(1, 'mimeType value must not be empty'))
    .transform((map) =>
      Object.fromEntries(Object.entries(map).map(([key, value]) => [key.toLowerCase(), value])),
    )
    .pipe(
      z.record(
        z
          .string()
          .regex(
            /^(\.[a-z0-9]+)+$/,
            'extension key must consist of one or more lowercase ".alphanumeric" segments (e.g. ".csv", ".tar.gz")',
          ),
        z.string().min(1, 'mimeType value must not be empty'),
      ),
    )
    .prefault({ '.csv': 'text/csv' })
    .describe(
      'Map of file extension suffix to canonical MIME type, used to override the SharePoint-reported ' +
        'mimeType. Keys are lowercased and must match one or more ".alphanumeric" segments ' +
        '(e.g. ".csv", ".tar.gz"). User-supplied values replace the default wholesale (no merge); ' +
        'include ".csv" in custom maps to retain the CSV fix.',
    ),
});

export type ProcessingConfig = z.infer<typeof ProcessingConfigSchema>;
