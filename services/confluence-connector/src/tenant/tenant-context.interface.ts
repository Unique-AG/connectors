import type { Logger } from 'pino';
import type { TenantConfig } from '../config/tenant-config-loader';
import type { TenantServiceRegistry } from './tenant-service-registry';

export interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly services: TenantServiceRegistry;
  readonly logger: Logger;
  isScanning: boolean;
}
