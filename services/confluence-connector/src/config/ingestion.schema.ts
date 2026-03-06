import { z } from 'zod';
import {
  IngestionMode,
  StoreInternallyMode,
  V1KeyFormatMode,
} from '../constants/ingestion.constants';

const IngestionModeSchema = z.enum([IngestionMode.Flat]).prefault(IngestionMode.Flat);

export const IngestionConfigSchema = z.object({
  ingestionMode: IngestionModeSchema.describe('Ingestion traversal mode'),
  scopeId: z.string().min(1).describe('Root scope ID for ingestion'),
  storeInternally: z
    .enum([StoreInternallyMode.Enabled, StoreInternallyMode.Disabled])
    .prefault(StoreInternallyMode.Enabled)
    .describe('Whether to store content internally in Unique'),
  useV1KeyFormat: z
    .enum([V1KeyFormatMode.Enabled, V1KeyFormatMode.Disabled])
    .prefault(V1KeyFormatMode.Disabled)
    .describe(
      'Use v1-compatible ingestion key format (spaceId_spaceKey/pageId) without tenant prefix',
    ),
});

export type IngestionConfig = z.infer<typeof IngestionConfigSchema>;
