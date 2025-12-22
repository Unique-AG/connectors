import { z } from 'zod';
import { ProcessingConfigSchema } from './processing.config';
import { SharepointConfigSchema } from './sharepoint.config';
import { UniqueConfigSchema } from './unique.config';

export const TenantConfigSchema = z.object({
  sharepoint: SharepointConfigSchema,
  unique: UniqueConfigSchema,
  processing: ProcessingConfigSchema,
});

export type TenantConfig = z.infer<typeof TenantConfigSchema>;
