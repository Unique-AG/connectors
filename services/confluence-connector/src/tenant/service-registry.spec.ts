import pino from 'pino';
import { describe, expect, it, vi } from 'vitest';
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

  describe('logger ownership', () => {
    it('registers and retrieves a service logger with tenantName and service bindings', () => {
      const registry = new ServiceRegistry();
      const baseLogger = pino({ level: 'silent' });
      const childSpy = vi.spyOn(baseLogger, 'child');
      const tenant = createMockTenant('acme');

      registry.registerTenantLogger('acme', baseLogger);

      tenantStorage.run(tenant, () => {
        const serviceLogger = registry.getServiceLogger(FooService);

        expect(serviceLogger).toBeDefined();
        expect(serviceLogger).not.toBe(baseLogger);
        expect(childSpy).toHaveBeenCalledWith({
          tenantName: 'acme',
          service: 'FooService',
        });
      });
    });

    it('isolates loggers between tenants', () => {
      const registry = new ServiceRegistry();
      const baseA = pino({ level: 'silent' });
      const baseB = pino({ level: 'silent' });
      const tenantA = createMockTenant('tenant-a');
      const tenantB = createMockTenant('tenant-b');

      registry.registerTenantLogger('tenant-a', baseA);
      registry.registerTenantLogger('tenant-b', baseB);

      tenantStorage.run(tenantA, () => {
        const loggerA = registry.getServiceLogger(FooService);
        expect(loggerA).toBeDefined();
        expect(loggerA).not.toBe(baseA);
        expect(loggerA).not.toBe(baseB);
      });
      tenantStorage.run(tenantB, () => {
        const loggerB = registry.getServiceLogger(FooService);
        expect(loggerB).toBeDefined();
        expect(loggerB).not.toBe(baseA);
        expect(loggerB).not.toBe(baseB);
      });
    });

    it('throws when called outside tenant execution scope', () => {
      const registry = new ServiceRegistry();
      registry.registerTenantLogger('acme', pino({ level: 'silent' }));

      expect(() => registry.getServiceLogger(FooService)).toThrow(
        'No tenant context — called outside of sync execution',
      );
    });

    it('throws when no logger is registered for the tenant', () => {
      const registry = new ServiceRegistry();
      const tenant = createMockTenant('acme');

      tenantStorage.run(tenant, () => {
        expect(() => registry.getServiceLogger(FooService)).toThrow(
          'No logger registered for tenant: acme',
        );
      });
    });
  });
});
