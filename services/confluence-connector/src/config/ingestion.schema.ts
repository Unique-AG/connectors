import { z } from 'zod';
import { EnabledDisabledMode, IngestionMode } from '../constants/ingestion.constants';

const IngestionModeSchema = z.enum([IngestionMode.Flat]).prefault(IngestionMode.Flat);

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
});

export type IngestionConfig = z.infer<typeof IngestionConfigSchema>;
