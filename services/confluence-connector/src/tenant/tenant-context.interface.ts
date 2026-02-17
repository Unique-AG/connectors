import type { TenantConfig } from '../config';

export interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  isScanning: boolean;
}
