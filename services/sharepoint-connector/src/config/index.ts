import { AppConfigNamespaced } from './app.config';
import { ProcessingConfigNamespaced } from './processing.config';
import { SharepointConfigNamespaced } from './sharepoint.config';
import { UniqueConfigNamespaced } from './unique.config';

export type Config = UniqueConfigNamespaced &
  ProcessingConfigNamespaced &
  SharepointConfigNamespaced &
  AppConfigNamespaced;
