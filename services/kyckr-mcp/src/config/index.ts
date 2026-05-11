import type { AppConfigNamespaced } from './app.config';
import type { KyckrConfigNamespaced } from './kyckr.config';

export * from './app.config';
export * from './kyckr.config';

export type ConfigNamespaced = AppConfigNamespaced & KyckrConfigNamespaced;
