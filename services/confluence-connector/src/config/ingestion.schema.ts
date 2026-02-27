import { z } from 'zod';
import { IngestFiles, IngestionMode } from '../constants/ingestion.constants';

const IngestionModeSchema = z.enum([IngestionMode.Flat]);

const IngestFilesSchema = z.enum([IngestFiles.Enabled, IngestFiles.Disabled]);

export const IngestionConfigSchema = z
  .object({
    ingestionMode: IngestionModeSchema.describe('Ingestion traversal mode'),
    scopeId: z.string().min(1).describe('Root scope ID for ingestion'),
    ingestFiles: IngestFilesSchema.describe('Whether file attachment ingestion is enabled'),
    allowedFileExtensions: z
      .array(z.string().min(1))
      .optional()
      .describe('File extensions to ingest (required when ingestFiles is enabled)'),
  })
  .refine(
    (data) =>
      data.ingestFiles !== IngestFiles.Enabled ||
      (data.allowedFileExtensions && data.allowedFileExtensions.length > 0),
    {
      message:
        'allowedFileExtensions is required and must not be empty when ingestFiles is enabled',
      path: ['allowedFileExtensions'],
    },
  );

export type IngestionConfig = z.infer<typeof IngestionConfigSchema>;
