import assert from 'node:assert';
import { AsyncLocalStorage } from 'node:async_hooks';
import type { TenantContext } from './tenant-context.interface';

export const tenantStorage = new AsyncLocalStorage<TenantContext>();

export function getCurrentTenant(): TenantContext {
  const tenant = tenantStorage.getStore();
  assert.ok(tenant, 'No tenant context — called outside of sync execution');
  return tenant;
}
