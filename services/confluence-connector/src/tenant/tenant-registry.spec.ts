import { describe, expect, it, vi } from 'vitest';
import type { NamedTenantConfig, TenantConfig } from '../config/tenant-config-loader';
import { getTenantConfigs } from '../config/tenant-config-loader';
import { TenantAuthFactory } from './tenant-auth.factory';
import type { TenantAuth } from './tenant-auth.interface';
import { TenantRegistry } from './tenant-registry';

vi.mock('../config/tenant-config-loader', () => ({
  getTenantConfigs: vi.fn(),
}));

vi.mock('./tenant-auth.factory');

function createMockTenantConfig(): TenantConfig {
  return {
    confluence: {
      instanceType: 'cloud',
      baseUrl: 'https://confluence.example.com',
      apiRateLimitPerMinute: 100,
      ingestSingleLabel: 'sync',
      ingestAllLabel: 'sync-all',
      auth: { mode: 'oauth_2lo', clientId: 'id', clientSecret: 'secret' },
    },
    unique: {},
    processing: {},
  } as unknown as TenantConfig;
}

function createMockAuth(): TenantAuth {
  return { getAccessToken: vi.fn().mockResolvedValue('mock-token') };
}

function createRegistry(configs: NamedTenantConfig[]): TenantRegistry {
  vi.mocked(getTenantConfigs).mockReturnValue(configs);

  const mockAuth = createMockAuth();
  const mockFactory = new TenantAuthFactory();
  vi.mocked(mockFactory.create).mockReturnValue(mockAuth);

  const registry = new TenantRegistry(mockFactory);
  registry.onModuleInit();
  return registry;
}

describe('TenantRegistry', () => {
  describe('onModuleInit', () => {
    it('registers tenants from configs', () => {
      const configs: NamedTenantConfig[] = [
        { name: 'tenant-a', config: createMockTenantConfig() },
        { name: 'tenant-b', config: createMockTenantConfig() },
      ];

      const registry = createRegistry(configs);

      expect(registry.size).toBe(2);
    });
  });

  describe('get', () => {
    it('returns the correct tenant by name', () => {
      const configA = createMockTenantConfig();
      const configs: NamedTenantConfig[] = [
        { name: 'tenant-a', config: configA },
        { name: 'tenant-b', config: createMockTenantConfig() },
      ];

      const registry = createRegistry(configs);
      const tenant = registry.get('tenant-a');

      expect(tenant.name).toBe('tenant-a');
      expect(tenant.config).toBe(configA);
      expect(tenant.isScanning).toBe(false);
    });

    it('throws for unknown tenant', () => {
      const registry = createRegistry([{ name: 'tenant-a', config: createMockTenantConfig() }]);

      expect(() => registry.get('unknown')).toThrow('Unknown tenant: unknown');
    });
  });

  describe('getAll', () => {
    it('returns all registered tenants', () => {
      const configs: NamedTenantConfig[] = [
        { name: 'tenant-a', config: createMockTenantConfig() },
        { name: 'tenant-b', config: createMockTenantConfig() },
        { name: 'tenant-c', config: createMockTenantConfig() },
      ];

      const registry = createRegistry(configs);
      const all = registry.getAll();

      expect(all).toHaveLength(3);
      expect(all.map((t) => t.name)).toEqual(['tenant-a', 'tenant-b', 'tenant-c']);
    });
  });

  describe('size', () => {
    it('returns the number of registered tenants', () => {
      const configs: NamedTenantConfig[] = [
        { name: 'tenant-a', config: createMockTenantConfig() },
        { name: 'tenant-b', config: createMockTenantConfig() },
      ];

      const registry = createRegistry(configs);

      expect(registry.size).toBe(2);
    });
  });
});
