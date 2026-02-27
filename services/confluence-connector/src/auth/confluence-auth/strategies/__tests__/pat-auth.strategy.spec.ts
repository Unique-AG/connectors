import { describe, expect, it } from 'vitest';
import { AuthMode } from '../../../../config/confluence.schema';
import type { TenantContext } from '../../../../tenant/tenant-context.interface';
import { tenantStorage } from '../../../../tenant/tenant-context.storage';
import { Redacted } from '../../../../utils/redacted';
import { PatAuthStrategy } from '../pat-auth.strategy';

const mockTenant: TenantContext = {
  name: 'test-tenant',
  config: {} as TenantContext['config'],
  isScanning: false,
};

describe('PatAuthStrategy', () => {
  const authConfig = {
    mode: AuthMode.PAT,
    token: new Redacted('my-personal-access-token'),
  };

  it('returns the unwrapped token value as accessToken', async () => {
    const strategy = new PatAuthStrategy(authConfig);

    const result = await tenantStorage.run(mockTenant, () => strategy.acquireToken());

    expect(result).toBe('my-personal-access-token');
  });

  it('returns the same token on multiple calls', async () => {
    const strategy = new PatAuthStrategy(authConfig);

    const first = await tenantStorage.run(mockTenant, () => strategy.acquireToken());
    const second = await tenantStorage.run(mockTenant, () => strategy.acquireToken());

    expect(first).toBe(second);
    expect(first).toBe('my-personal-access-token');
  });
});
