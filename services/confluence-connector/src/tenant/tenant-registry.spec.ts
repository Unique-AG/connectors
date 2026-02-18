import type pino from 'pino';
import { describe, expect, it, vi } from 'vitest';
import { ConfluenceAuth, ConfluenceAuthFactory } from '../auth/confluence-auth';
import { UniqueAuth, UniqueAuthFactory } from '../auth/unique-auth';
import type { NamedTenantConfig, TenantConfig } from '../config/tenant-config-loader';
import { getTenantConfigs } from '../config/tenant-config-loader';
import { ConfluenceApiClient, ConfluenceApiClientFactory } from '../confluence-api';
import { ServiceRegistry } from './service-registry';
import { tenantStorage } from './tenant-context.storage';
import { TenantRegistry } from './tenant-registry';

const { mockChildLogger, mockRoot } = vi.hoisted(() => {
  const mockChildLogger = {
    info: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
    child: vi.fn().mockImplementation((bindings: Record<string, string>) => ({
      info: vi.fn(),
      error: vi.fn(),
      warn: vi.fn(),
      bindings: () => bindings,
    })),
  } as unknown as pino.Logger;
  const mockRoot = {
    child: vi.fn().mockReturnValue(mockChildLogger),
  } as unknown as pino.Logger;
  return { mockChildLogger, mockRoot };
});

vi.mock('nestjs-pino', async () => {
  const actual = await vi.importActual('nestjs-pino');
  return {
    ...actual,
    PinoLogger: { root: mockRoot },
  };
});

vi.mock('../config/tenant-config-loader', () => ({
  getTenantConfigs: vi.fn(),
}));

vi.mock('../auth/confluence-auth/confluence-auth.factory');
vi.mock('../auth/unique-auth/unique-auth.factory');
vi.mock('../confluence-api/confluence-api-client.factory');

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

function createMockAuth(): ConfluenceAuth {
  return { acquireToken: vi.fn().mockResolvedValue('mock-token') };
}

function createMockUniqueAuth(): UniqueAuth {
  return {
    getHeaders: vi.fn().mockResolvedValue({ Authorization: 'Bearer mock' }),
    close: vi.fn().mockResolvedValue(undefined),
  } as unknown as UniqueAuth;
}

function createRegistry(configs: NamedTenantConfig[]): {
  registry: TenantRegistry;
  serviceRegistry: ServiceRegistry;
} {
  vi.mocked(getTenantConfigs).mockReturnValue(configs);

  const mockFactory = new ConfluenceAuthFactory({} as ServiceRegistry);
  vi.mocked(mockFactory.createAuthStrategy).mockImplementation(() => createMockAuth());

  const mockApiClientFactory = new ConfluenceApiClientFactory({} as ServiceRegistry);
  vi.mocked(mockApiClientFactory.create).mockImplementation(() => ({}) as never);

  const mockUniqueFactory = new UniqueAuthFactory({} as ServiceRegistry);
  vi.mocked(mockUniqueFactory.create).mockImplementation(() => createMockUniqueAuth());

  const serviceRegistry = new ServiceRegistry();
  const registry = new TenantRegistry(
    mockFactory,
    mockApiClientFactory,
    mockUniqueFactory,
    serviceRegistry,
  );
  registry.onModuleInit();
  return { registry, serviceRegistry };
}

describe('TenantRegistry', () => {
  describe('onModuleInit', () => {
    it('registers tenants from configs', () => {
      const configs: NamedTenantConfig[] = [
        { name: 'tenant-a', config: createMockTenantConfig() },
        { name: 'tenant-b', config: createMockTenantConfig() },
      ];

      const { registry } = createRegistry(configs);

      expect(registry.tenantCount).toBe(2);
    });

    it('creates a pino child logger per tenant with tenantName binding', () => {
      const configs: NamedTenantConfig[] = [
        { name: 'tenant-a', config: createMockTenantConfig() },
        { name: 'tenant-b', config: createMockTenantConfig() },
      ];

      createRegistry(configs);

      expect(mockRoot.child).toHaveBeenCalledWith({ tenantName: 'tenant-a' });
      expect(mockRoot.child).toHaveBeenCalledWith({ tenantName: 'tenant-b' });
    });

    it('logs tenant registration via pino child logger', () => {
      createRegistry([{ name: 'tenant-a', config: createMockTenantConfig() }]);

      expect(mockChildLogger.info).toHaveBeenCalledWith('Tenant registered');
    });

    it('calls ConfluenceAuthFactory.createAuthStrategy for each tenant', () => {
      const configA = createMockTenantConfig();
      const configB = createMockTenantConfig();

      vi.mocked(getTenantConfigs).mockReturnValue([
        { name: 'tenant-a', config: configA },
        { name: 'tenant-b', config: configB },
      ]);

      const mockFactory = new ConfluenceAuthFactory({} as ServiceRegistry);
      vi.mocked(mockFactory.createAuthStrategy).mockReturnValue(createMockAuth());

      const mockApiClientFactory = new ConfluenceApiClientFactory({} as ServiceRegistry);
      vi.mocked(mockApiClientFactory.create).mockReturnValue({} as never);

      const mockUniqueFactory = new UniqueAuthFactory({} as ServiceRegistry);
      vi.mocked(mockUniqueFactory.create).mockReturnValue(createMockUniqueAuth());

      const serviceRegistry = new ServiceRegistry();
      const registry = new TenantRegistry(
        mockFactory,
        mockApiClientFactory,
        mockUniqueFactory,
        serviceRegistry,
      );
      registry.onModuleInit();

      expect(mockFactory.createAuthStrategy).toHaveBeenCalledWith(configA.confluence);
      expect(mockFactory.createAuthStrategy).toHaveBeenCalledWith(configB.confluence);
    });

    it('calls UniqueAuthFactory.create for each tenant', () => {
      const configA = createMockTenantConfig();
      const configB = createMockTenantConfig();

      vi.mocked(getTenantConfigs).mockReturnValue([
        { name: 'tenant-a', config: configA },
        { name: 'tenant-b', config: configB },
      ]);

      const mockFactory = new ConfluenceAuthFactory({} as ServiceRegistry);
      vi.mocked(mockFactory.createAuthStrategy).mockReturnValue(createMockAuth());

      const mockApiClientFactory = new ConfluenceApiClientFactory({} as ServiceRegistry);
      vi.mocked(mockApiClientFactory.create).mockReturnValue({} as never);

      const mockUniqueFactory = new UniqueAuthFactory({} as ServiceRegistry);
      vi.mocked(mockUniqueFactory.create).mockReturnValue(createMockUniqueAuth());

      const serviceRegistry = new ServiceRegistry();
      const registry = new TenantRegistry(
        mockFactory,
        mockApiClientFactory,
        mockUniqueFactory,
        serviceRegistry,
      );
      registry.onModuleInit();

      expect(mockUniqueFactory.create).toHaveBeenCalledWith(configA.unique);
      expect(mockUniqueFactory.create).toHaveBeenCalledWith(configB.unique);
    });

    it('calls ConfluenceApiClientFactory.create for each tenant', () => {
      const configA = createMockTenantConfig();
      const configB = createMockTenantConfig();

      vi.mocked(getTenantConfigs).mockReturnValue([
        { name: 'tenant-a', config: configA },
        { name: 'tenant-b', config: configB },
      ]);

      const mockFactory = new ConfluenceAuthFactory({} as ServiceRegistry);
      vi.mocked(mockFactory.createAuthStrategy).mockReturnValue(createMockAuth());

      const mockApiClientFactory = new ConfluenceApiClientFactory({} as ServiceRegistry);
      vi.mocked(mockApiClientFactory.create).mockReturnValue({} as never);

      const mockUniqueFactory = new UniqueAuthFactory({} as ServiceRegistry);
      vi.mocked(mockUniqueFactory.create).mockReturnValue(createMockUniqueAuth());

      const serviceRegistry = new ServiceRegistry();
      const registry = new TenantRegistry(
        mockFactory,
        mockApiClientFactory,
        mockUniqueFactory,
        serviceRegistry,
      );
      registry.onModuleInit();

      expect(mockApiClientFactory.create).toHaveBeenCalledWith(configA.confluence);
      expect(mockApiClientFactory.create).toHaveBeenCalledWith(configB.confluence);
    });

    it('registers ConfluenceAuth, UniqueAuth, and ConfluenceApiClient in ServiceRegistry for each tenant', () => {
      const configs: NamedTenantConfig[] = [{ name: 'tenant-a', config: createMockTenantConfig() }];

      const { registry, serviceRegistry } = createRegistry(configs);
      const tenant = registry.getTenant('tenant-a');

      tenantStorage.run(tenant, () => {
        expect(serviceRegistry.getService(ConfluenceAuth)).toBeDefined();
        expect(serviceRegistry.getService(UniqueAuth)).toBeDefined();
        expect(serviceRegistry.getService(ConfluenceApiClient)).toBeDefined();
      });
    });

    it('registers tenant base logger in ServiceRegistry for each tenant', () => {
      const configs: NamedTenantConfig[] = [
        { name: 'tenant-a', config: createMockTenantConfig() },
        { name: 'tenant-b', config: createMockTenantConfig() },
      ];

      const { registry, serviceRegistry } = createRegistry(configs);

      tenantStorage.run(registry.getTenant('tenant-a'), () => {
        const loggerA = serviceRegistry.getServiceLogger({ name: 'TestService' });
        expect(loggerA).toBeDefined();
        expect(loggerA.bindings()).toMatchObject({
          tenantName: 'tenant-a',
          service: 'TestService',
        });
      });

      tenantStorage.run(registry.getTenant('tenant-b'), () => {
        const loggerB = serviceRegistry.getServiceLogger({ name: 'TestService' });
        expect(loggerB).toBeDefined();
        expect(loggerB.bindings()).toMatchObject({
          tenantName: 'tenant-b',
          service: 'TestService',
        });
      });
    });
  });

  describe('getTenant', () => {
    it('returns the correct tenant by name', () => {
      const configA = createMockTenantConfig();
      const configs: NamedTenantConfig[] = [
        { name: 'tenant-a', config: configA },
        { name: 'tenant-b', config: createMockTenantConfig() },
      ];

      const { registry } = createRegistry(configs);
      const tenant = registry.getTenant('tenant-a');

      expect(tenant.name).toBe('tenant-a');
      expect(tenant.config).toBe(configA);
      expect(tenant.isScanning).toBe(false);
    });

    it('throws for unknown tenant', () => {
      const { registry } = createRegistry([{ name: 'tenant-a', config: createMockTenantConfig() }]);

      expect(() => registry.getTenant('unknown')).toThrow('Unknown tenant: unknown');
    });
  });

  describe('getAllTenants', () => {
    it('returns all registered tenants', () => {
      const configs: NamedTenantConfig[] = [
        { name: 'tenant-a', config: createMockTenantConfig() },
        { name: 'tenant-b', config: createMockTenantConfig() },
        { name: 'tenant-c', config: createMockTenantConfig() },
      ];

      const { registry } = createRegistry(configs);
      const all = registry.getAllTenants();

      expect(all).toHaveLength(3);
      expect(all.map((t) => t.name)).toEqual(['tenant-a', 'tenant-b', 'tenant-c']);
    });
  });

  describe('tenantCount', () => {
    it('returns the number of registered tenants', () => {
      const configs: NamedTenantConfig[] = [
        { name: 'tenant-a', config: createMockTenantConfig() },
        { name: 'tenant-b', config: createMockTenantConfig() },
      ];

      const { registry } = createRegistry(configs);

      expect(registry.tenantCount).toBe(2);
    });
  });

  describe('run', () => {
    it('sets AsyncLocalStorage context for the duration of the callback', () => {
      const { registry } = createRegistry([{ name: 'acme', config: createMockTenantConfig() }]);
      const tenant = registry.getTenant('acme');

      let captured: string | undefined;
      registry.run(tenant, () => {
        captured = tenantStorage.getStore()?.name;
      });

      expect(captured).toBe('acme');
    });
  });
});
