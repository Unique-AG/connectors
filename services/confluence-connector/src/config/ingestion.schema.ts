import { z } from 'zod';
import { IngestionMode } from '../constants/ingestion.constants';

const IngestionModeSchema = z.enum([IngestionMode.Flat]);

export const IngestionConfigSchema = z.object({
  ingestionMode: IngestionModeSchema.describe('Ingestion traversal mode'),
  scopeId: z.string().min(1).describe('Root scope ID for ingestion'),
});

export type IngestionConfig = z.infer<typeof IngestionConfigSchema>;
