import { AsyncLocalStorage } from 'node:async_hooks';
import type { TenantContext } from './tenant-context.interface';

export const tenantStorage = new AsyncLocalStorage<TenantContext>();

export function getCurrentTenant(): TenantContext {
  const tenant = tenantStorage.getStore();
  if (!tenant) {
    throw new Error('No tenant context — called outside of sync execution');
  }
  return tenant;
}
