import { describe, expect, it } from 'vitest';
import type { TenantContext } from './tenant-context.interface';
import { getCurrentTenant, getTenantService, tenantStorage } from './tenant-context.storage';
import { TenantServiceRegistry } from './tenant-service-registry';

abstract class StubService {
  public abstract execute(): string;
}

function createMockTenant(overrides: Partial<TenantContext> = {}): TenantContext {
  return {
    name: 'acme',
    services: new TenantServiceRegistry(),
    ...overrides,
  } as TenantContext;
}

describe('tenantStorage', () => {
  const mockTenant = createMockTenant();

  describe('getCurrentTenant', () => {
    it('throws when called outside of sync execution', () => {
      expect(() => getCurrentTenant()).toThrow(
        'No tenant context — called outside of sync execution',
      );
    });

    it('returns the tenant context set by tenantStorage.run()', async () => {
      await tenantStorage.run(mockTenant, async () => {
        expect(getCurrentTenant()).toBe(mockTenant);
      });
    });

    it('propagates context through nested async calls', async () => {
      const nestedRead = async (): Promise<TenantContext> => getCurrentTenant();

      await tenantStorage.run(mockTenant, async () => {
        const result = await nestedRead();
        expect(result).toBe(mockTenant);
      });
    });

    it('isolates context between concurrent runs', async () => {
      const tenantA = createMockTenant({ name: 'tenant-a' });
      const tenantB = createMockTenant({ name: 'tenant-b' });

      const results: string[] = [];

      await Promise.all([
        tenantStorage.run(tenantA, async () => {
          await new Promise((resolve) => setTimeout(resolve, 10));
          results.push(getCurrentTenant().name);
        }),
        tenantStorage.run(tenantB, async () => {
          results.push(getCurrentTenant().name);
        }),
      ]);

      expect(results).toContain('tenant-a');
      expect(results).toContain('tenant-b');
    });
  });

  describe('getTenantService', () => {
    it('throws when called outside of tenant context', () => {
      expect(() => getTenantService(StubService)).toThrow(
        'No tenant context — called outside of sync execution',
      );
    });

    it('returns the service registered in the tenant context', async () => {
      const stubImpl = { execute: () => 'hello' } as StubService;
      const registry = new TenantServiceRegistry();
      registry.set(StubService, stubImpl);
      const tenant = createMockTenant({ services: registry });

      await tenantStorage.run(tenant, async () => {
        expect(getTenantService(StubService)).toBe(stubImpl);
      });
    });
  });
});
