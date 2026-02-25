export { type AppConfig, type AppConfigNamespaced, appConfig } from './app.config';
export type { ConfluenceConfig } from './confluence.schema';
export type { ProcessingConfig } from './processing.schema';
export {
  type ConfluenceConfigNamespaced,
  confluenceConfig,
  getTenantConfigs,
  type ProcessingConfigNamespaced,
  processingConfig,
  type TenantConfig,
  type UniqueConfigNamespaced,
  uniqueConfig,
} from './tenant-config-loader';
export type { UniqueConfig } from './unique.schema';

import type { AppConfigNamespaced } from './app.config';
import type {
  ConfluenceConfigNamespaced,
  ProcessingConfigNamespaced,
  UniqueConfigNamespaced,
} from './tenant-config-loader';

export type Config = ConfluenceConfigNamespaced &
  UniqueConfigNamespaced &
  ProcessingConfigNamespaced &
  AppConfigNamespaced;
