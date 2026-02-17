import { describe, expect, it, vi } from 'vitest';
import { AuthMode } from '../../../config/confluence.schema';
import { ServiceRegistry } from '../../../tenant/service-registry';
import { tenantStorage } from '../../../tenant/tenant-context.storage';
import type { TenantContext } from '../../../tenant/tenant-context.interface';
import { Redacted } from '../../../utils/redacted';
import { PatAuthStrategy } from './pat-auth.strategy';

const mockLogger = { info: vi.fn(), error: vi.fn() };
const mockServiceRegistry = {
  getServiceLogger: vi.fn().mockReturnValue(mockLogger),
} as unknown as ServiceRegistry;

const mockTenant: TenantContext = {
  name: 'test-tenant',
  config: {} as TenantContext['config'],
  logger: {} as TenantContext['logger'],
  isScanning: false,
};

describe('PatAuthStrategy', () => {
  const authConfig = {
    mode: AuthMode.PAT,
    token: new Redacted('my-personal-access-token'),
  };

  it('returns the unwrapped token value as accessToken', async () => {
    const strategy = new PatAuthStrategy(authConfig, mockServiceRegistry);

    const result = await tenantStorage.run(mockTenant, () => strategy.acquireToken());

    expect(result).toBe('my-personal-access-token');
  });

  it('returns the same token on multiple calls', async () => {
    const strategy = new PatAuthStrategy(authConfig, mockServiceRegistry);

    const first = await tenantStorage.run(mockTenant, () => strategy.acquireToken());
    const second = await tenantStorage.run(mockTenant, () => strategy.acquireToken());

    expect(first).toBe(second);
    expect(first).toBe('my-personal-access-token');
  });
});
