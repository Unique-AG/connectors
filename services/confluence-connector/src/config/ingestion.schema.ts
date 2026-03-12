import { z } from 'zod';
import {
  DEFAULT_ALLOWED_EXTENSIONS,
  DEFAULT_MAX_FILE_SIZE_BYTES,
} from '../constants/defaults.constants';
import { EnabledDisabledMode, IngestionMode } from '../constants/ingestion.constants';

const IngestionModeSchema = z.enum([IngestionMode.Flat]).prefault(IngestionMode.Flat);

function getMaxFileSizeBytesDefault(): number {
  const envValue = process.env.MAX_FILE_SIZE_BYTES;
  if (envValue) {
    const parsed = Number(envValue);
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return DEFAULT_MAX_FILE_SIZE_BYTES;
}

const AttachmentConfigSchema = z.object({
  enabled: z
    .enum([EnabledDisabledMode.Enabled, EnabledDisabledMode.Disabled])
    .prefault(EnabledDisabledMode.Enabled)
    .transform((v) => v === EnabledDisabledMode.Enabled)
    .describe('Whether to ingest file attachments from Confluence pages'),
  allowedExtensions: z
    .array(z.string().min(1))
    .prefault([...DEFAULT_ALLOWED_EXTENSIONS])
    .describe('File extensions to include when ingesting attachments'),
  maxFileSizeBytes: z
    .number()
    .int()
    .positive()
    .prefault(getMaxFileSizeBytesDefault())
    .describe('Maximum file size in bytes for attachment ingestion'),
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

export type IngestionConfig = z.infer<typeof IngestionConfigSchema>;
export type AttachmentConfig = z.infer<typeof AttachmentConfigSchema>;
