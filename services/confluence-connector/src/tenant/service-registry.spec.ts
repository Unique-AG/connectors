import { describe, expect, it } from 'vitest';
import { ServiceRegistry } from './service-registry';
import type { TenantContext } from './tenant-context.interface';
import { tenantStorage } from './tenant-context.storage';

abstract class FooService {
  public abstract doFoo(): string;
}

abstract class BarService {
  public abstract doBar(): number;
}

function createMockTenant(name: string): TenantContext {
  return { name } as TenantContext;
}

describe('ServiceRegistry', () => {
  describe('register', () => {
    it('registers a service for a tenant', () => {
      const registry = new ServiceRegistry();
      const fooImpl = { doFoo: () => 'hello' } as FooService;
      const tenant = createMockTenant('acme');

      registry.register('acme', FooService, fooImpl);

      tenantStorage.run(tenant, () => {
        expect(registry.getService(FooService)).toBe(fooImpl);
      });
    });

    it('registers multiple services for the same tenant', () => {
      const registry = new ServiceRegistry();
      const fooImpl = { doFoo: () => 'hello' } as FooService;
      const barImpl = { doBar: () => 42 } as BarService;
      const tenant = createMockTenant('acme');

      registry.register('acme', FooService, fooImpl);
      registry.register('acme', BarService, barImpl);

      tenantStorage.run(tenant, () => {
        expect(registry.getService(FooService)).toBe(fooImpl);
        expect(registry.getService(BarService)).toBe(barImpl);
      });
    });

    it('overwrites a previous registration for the same key', () => {
      const registry = new ServiceRegistry();
      const first = { doFoo: () => 'first' } as FooService;
      const second = { doFoo: () => 'second' } as FooService;
      const tenant = createMockTenant('acme');

      registry.register('acme', FooService, first);
      registry.register('acme', FooService, second);

      tenantStorage.run(tenant, () => {
        expect(registry.getService(FooService)).toBe(second);
      });
    });

    it('isolates services between tenants', () => {
      const registry = new ServiceRegistry();
      const fooA = { doFoo: () => 'a' } as FooService;
      const fooB = { doFoo: () => 'b' } as FooService;
      const tenantA = createMockTenant('tenant-a');
      const tenantB = createMockTenant('tenant-b');

      registry.register('tenant-a', FooService, fooA);
      registry.register('tenant-b', FooService, fooB);

      tenantStorage.run(tenantA, () => {
        expect(registry.getService(FooService)).toBe(fooA);
      });
      tenantStorage.run(tenantB, () => {
        expect(registry.getService(FooService)).toBe(fooB);
      });
    });
  });

  describe('getService', () => {
    it('throws when called outside tenant execution scope', () => {
      const registry = new ServiceRegistry();

      expect(() => registry.getService(FooService)).toThrow(
        'No tenant context — called outside of sync execution',
      );
    });

    it('throws when no services are registered for the tenant', () => {
      const registry = new ServiceRegistry();
      const tenant = createMockTenant('acme');

      tenantStorage.run(tenant, () => {
        expect(() => registry.getService(FooService)).toThrow(
          'No services registered for tenant: acme',
        );
      });
    });

    it('throws when the requested service is not registered', () => {
      const registry = new ServiceRegistry();
      const tenant = createMockTenant('acme');
      registry.register('acme', BarService, { doBar: () => 42 } as BarService);

      tenantStorage.run(tenant, () => {
        expect(() => registry.getService(FooService)).toThrow(
          'Service not found for tenant "acme": FooService',
        );
      });
    });
  });
});
