import type { AppConfigNamespaced } from './app.config';
import type { TemenosConfigNamespaced } from './temenos.config';

export * from './app.config';
export * from './temenos.config';

export type ConfigNamespaced = AppConfigNamespaced & TemenosConfigNamespaced;
