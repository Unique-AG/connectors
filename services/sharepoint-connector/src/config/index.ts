import { HealthConfigNamespaced } from './health.config';
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
  ProxyConfigNamespaced &
  HealthConfigNamespaced;

export * from './health.config';
export * from './proxy.config';
