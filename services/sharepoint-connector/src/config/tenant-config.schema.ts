import { z } from 'zod';
import { ProcessingConfigSchema } from './processing.schema';
import { SharepointConfigSchema } from './sharepoint.schema';
import { UniqueConfigSchema } from './unique.schema';

export const TenantConfigSchema = z.object({
  sharepoint: SharepointConfigSchema,
  unique: UniqueConfigSchema,
  processing: ProcessingConfigSchema,
});

export type TenantConfig = z.infer<typeof TenantConfigSchema>;
