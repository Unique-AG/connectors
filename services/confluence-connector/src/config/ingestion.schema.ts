import { z } from 'zod';
import {
  DEFAULT_ALLOWED_EXTENSIONS,
  DEFAULT_MAX_FILE_SIZE_MB,
} from '../constants/defaults.constants';
import { EnabledDisabledMode, IngestionMode } from '../constants/ingestion.constants';

const IngestionModeSchema = z.enum([IngestionMode.Flat]).prefault(IngestionMode.Flat);


const AttachmentConfigSchema = z.object({
  ingest: z
    .enum([EnabledDisabledMode.Enabled, EnabledDisabledMode.Disabled])
    .prefault(EnabledDisabledMode.Enabled)
    .transform((v) => v === EnabledDisabledMode.Enabled)
    .describe('Whether to ingest file attachments from Confluence pages'),
  allowedExtensions: z
    .array(z.string().min(1))
    .prefault([...DEFAULT_ALLOWED_EXTENSIONS])
    .describe('File extensions to include when ingesting attachments'),
  maxFileSizeMb: z
    .number()
    .int()
    .positive()
    .prefault(DEFAULT_MAX_FILE_SIZE_MB)
    .describe('Maximum file size in megabytes for attachment ingestion'),
});

export const IngestionConfigSchema = z.object({
  ingestionMode: IngestionModeSchema.describe('Ingestion traversal mode'),
  scopeId: z.string().min(1).describe('Root scope ID for ingestion'),
  storeInternally: z
    .enum([EnabledDisabledMode.Enabled, EnabledDisabledMode.Disabled])
    .prefault(EnabledDisabledMode.Enabled)
    .transform((v) => v === EnabledDisabledMode.Enabled)
    .describe('Whether to store content internally in Unique'),
  useV1KeyFormat: z
    .enum([EnabledDisabledMode.Enabled, EnabledDisabledMode.Disabled])
    .prefault(EnabledDisabledMode.Disabled)
    .transform((v) => v === EnabledDisabledMode.Enabled)
    .describe(
      'Use v1-compatible ingestion key format (spaceId_spaceKey/pageId) without tenant prefix',
    ),
  attachments: AttachmentConfigSchema.prefault({}).describe(
    'Configuration for file attachment ingestion',
  ),
});

export const BYTES_PER_MB = 1024 * 1024;

export type IngestionConfig = z.infer<typeof IngestionConfigSchema>;
export type AttachmentConfig = z.infer<typeof AttachmentConfigSchema>;