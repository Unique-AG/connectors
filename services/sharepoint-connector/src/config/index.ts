import {
  AppConfigNamespaced,
  ProcessingConfigNamespaced,
  SharepointConfigNamespaced,
  UniqueConfigNamespaced,
} from './tenant-config-loader';

export type Config = UniqueConfigNamespaced &
  ProcessingConfigNamespaced &
  SharepointConfigNamespaced &
  AppConfigNamespaced;
