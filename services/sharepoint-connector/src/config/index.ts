import { ProxyConfigNamespaced } from './proxy.config';
import {
  AppConfigNamespaced,
  ProcessingConfigNamespaced,
  SharepointConfigNamespaced,
  UniqueConfigNamespaced,
} from './tenant-config-loader';

export type Config = UniqueConfigNamespaced &
  ProcessingConfigNamespaced &
  SharepointConfigNamespaced &
  AppConfigNamespaced &
  ProxyConfigNamespaced;

export * from './proxy.config';
