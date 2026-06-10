import { describe, expect, it } from 'vitest';
import { AuthMode } from '../../../../config/confluence.schema';
import type { TenantContext } from '../../../../tenant/tenant-context.interface';
import { tenantStorage } from '../../../../tenant/tenant-context.storage';
import { Redacted } from '../../../../utils/redacted';
import { PatAuthStrategy } from '../pat-auth.strategy';

const mockTenant: TenantContext = {
  name: 'test-tenant',
  config: {} as TenantContext['config'],
  status: 'active',
  isScanning: false,
};

describe('PatAuthStrategy', () => {
  const authConfig = {
    mode: AuthMode.Pat,
    token: new Redacted('my-personal-access-token'),
  };

  it('returns a Bearer authorization header with the unwrapped token', async () => {
    const strategy = new PatAuthStrategy(authConfig);

    const result = await tenantStorage.run(mockTenant, () => strategy.getAuthorizationHeader());

    expect(result).toBe('Bearer my-personal-access-token');
  });

  it('returns the same header on multiple calls', async () => {
    const strategy = new PatAuthStrategy(authConfig);

    const first = await tenantStorage.run(mockTenant, () => strategy.getAuthorizationHeader());
    const second = await tenantStorage.run(mockTenant, () => strategy.getAuthorizationHeader());

    expect(first).toBe(second);
    expect(first).toBe('Bearer my-personal-access-token');
  });
});
