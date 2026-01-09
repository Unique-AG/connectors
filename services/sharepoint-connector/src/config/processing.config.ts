import { registerAs } from '@nestjs/config';
import { type ProcessingConfig, ProcessingConfigSchema } from './processing.schema';
import { getTenantConfig } from './tenant-config-loader';

export const processingConfig = registerAs('processing', (): ProcessingConfig => {
  return ProcessingConfigSchema.parse(getTenantConfig().processing);
});

export interface ProcessingConfigNamespaced {
  processing: ProcessingConfig;
}
