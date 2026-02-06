import {
  AppConfigNamespaced,
  ConfluenceConfigNamespaced,
  ProcessingConfigNamespaced,
  UniqueConfigNamespaced,
} from './tenant-config-loader';

export type Config = ConfluenceConfigNamespaced &
  UniqueConfigNamespaced &
  ProcessingConfigNamespaced &
  AppConfigNamespaced;

export * from './tenant-config-loader';
