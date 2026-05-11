import type { AppConfigNamespaced } from './app.config';
import type { KyckrConfigNamespaced } from './kyckr.config';
import type { LogsConfigNamespaced } from './logs.config';

export * from './app.config';
export * from './kyckr.config';
export * from './logs.config';

export type ConfigNamespaced = AppConfigNamespaced & KyckrConfigNamespaced & LogsConfigNamespaced;
