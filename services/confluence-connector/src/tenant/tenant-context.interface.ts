import type { LoadedTenantStatus, TenantConfig } from '../config';

export interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly status: LoadedTenantStatus;
  isScanning: boolean;
}
