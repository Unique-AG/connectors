import type { Logger } from 'pino';
import type { TenantConfig } from '../config/tenant-config-loader';

export interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly logger: Logger;
  isScanning: boolean;
}
