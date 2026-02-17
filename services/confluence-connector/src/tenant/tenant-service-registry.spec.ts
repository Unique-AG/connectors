import { describe, expect, it } from 'vitest';
import { TenantServiceRegistry } from './tenant-service-registry';

abstract class FooService {
  public abstract doFoo(): string;
}

abstract class BarService {
  public abstract doBar(): number;
}

describe('TenantServiceRegistry', () => {
  describe('set', () => {
    it('returns the registry for chaining', () => {
      const registry = new TenantServiceRegistry();
      const fooImpl = { doFoo: () => 'hello' } as FooService;

      const result = registry.set(FooService, fooImpl);

      expect(result).toBe(registry);
    });
  });

  describe('get', () => {
    it('returns the instance previously stored with set', () => {
      const registry = new TenantServiceRegistry();
      const fooImpl = { doFoo: () => 'hello' } as FooService;

      registry.set(FooService, fooImpl);

      expect(registry.get(FooService)).toBe(fooImpl);
    });

    it('throws when the service has not been registered', () => {
      const registry = new TenantServiceRegistry();

      expect(() => registry.get(FooService)).toThrow(
        'Service not found in tenant registry: FooService',
      );
    });

    it('retrieves distinct services by their abstract class key', () => {
      const registry = new TenantServiceRegistry();
      const fooImpl = { doFoo: () => 'hello' } as FooService;
      const barImpl = { doBar: () => 42 } as BarService;

      registry.set(FooService, fooImpl).set(BarService, barImpl);

      expect(registry.get(FooService)).toBe(fooImpl);
      expect(registry.get(BarService)).toBe(barImpl);
    });

    it('overwrites a previous registration for the same key', () => {
      const registry = new TenantServiceRegistry();
      const first = { doFoo: () => 'first' } as FooService;
      const second = { doFoo: () => 'second' } as FooService;

      registry.set(FooService, first);
      registry.set(FooService, second);

      expect(registry.get(FooService)).toBe(second);
    });
  });

  describe('has', () => {
    it('returns false when the service has not been registered', () => {
      const registry = new TenantServiceRegistry();

      expect(registry.has(FooService)).toBe(false);
    });

    it('returns true after the service has been registered', () => {
      const registry = new TenantServiceRegistry();
      registry.set(FooService, { doFoo: () => 'hello' } as FooService);

      expect(registry.has(FooService)).toBe(true);
    });
  });
});
