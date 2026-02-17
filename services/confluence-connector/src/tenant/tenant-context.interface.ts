import type { Logger } from 'pino';
import type { TenantConfig } from '../config/tenant-config-loader';
import type { TenantAuth } from './tenant-auth';
import type { TenantServiceRegistry } from './tenant-service-registry';

export interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly logger: Logger;
  readonly auth: TenantAuth;
  readonly services: TenantServiceRegistry;
  isScanning: boolean;
}
