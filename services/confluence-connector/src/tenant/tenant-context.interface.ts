import type { Logger } from '@nestjs/common';
import type { TenantConfig } from '../config/tenant-config-loader';
import type { TenantAuth } from './tenant-auth.interface';

export interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly logger: Logger;
  readonly auth: TenantAuth;
  isScanning: boolean;
}
