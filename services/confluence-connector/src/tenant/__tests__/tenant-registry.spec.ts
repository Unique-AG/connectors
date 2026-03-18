import { UniqueApiClient } from '@unique-ag/unique-api';
import { describe, expect, it, vi } from 'vitest';
import { ConfluenceAuth, ConfluenceAuthFactory } from '../../auth/confluence-auth';
import type { NamedTenantConfig, TenantConfig } from '../../config/tenant-config-loader';
import { getDeletedTenantConfigs, getTenantConfigs } from '../../config/tenant-config-loader';
import { ConfluenceApiClient, ConfluenceApiClientFactory } from '../../confluence-api';
import { ServiceRegistry } from '../service-registry';
import { tenantStorage } from '../tenant-context.storage';
import { TenantDeleteService } from '../tenant-delete.service';
import { TenantRegistry } from '../tenant-registry';

const mockLogger = vi.hoisted(() => ({
  log: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

vi.mock('@nestjs/common', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nestjs/common')>();
  return {
    ...actual,
    Logger: vi.fn().mockImplementation(() => mockLogger),
  };
});

vi.mock('../../config/tenant-config-loader', () => ({
  getTenantConfigs: vi.fn(),
  getDeletedTenantConfigs: vi.fn().mockReturnValue([]),
}));

vi.mock('../../auth/confluence-auth/confluence-auth.factory');
vi.mock('../../confluence-api/confluence-api-client.factory');

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
    unique: {
      serviceAuthMode: 'cluster_local',
      serviceExtraHeaders: { 'x-company-id': 'company-1', 'x-user-id': 'user-1' },
      ingestionServiceBaseUrl: 'https://ingestion.example.com',
      scopeManagementServiceBaseUrl: 'https://scope.example.com',
      apiRateLimitPerMinute: 100,
    },
    ingestion: {
      scopeId: 'scope-1',
      storeInternally: true,
      useV1KeyFormat: false,
    },
    processing: {},
  } as unknown as TenantConfig;
}

function createMockAuth(): ConfluenceAuth {
  return { acquireToken: vi.fn().mockResolvedValue('mock-token') };
}

function createMockUniqueApiClient() {
  return {
    auth: {},
    scopes: {
      getById: vi.fn(),
      listChildren: vi.fn(),
      delete: vi.fn(),
    },
    files: {
      getByKeys: vi.fn(),
      getByKeyPrefix: vi.fn(),
      getCountByKeyPrefix: vi.fn(),
      getContentIdsByScope: vi.fn(),
      delete: vi.fn(),
      deleteByIds: vi.fn(),
      deleteByKeyPrefix: vi.fn(),
    },
    users: {},
    groups: {},
    ingestion: { performFileDiff: vi.fn(), registerContent: vi.fn(), finalizeIngestion: vi.fn() },
    close: vi.fn(),
  };
}

function createRegistry(
  configs: NamedTenantConfig[],
  deletedConfigs: NamedTenantConfig[] = [],
): {
  registry: TenantRegistry;
  serviceRegistry: ServiceRegistry;
  mockUniqueApiFactory: { create: ReturnType<typeof vi.fn> };
} {
  vi.mocked(getTenantConfigs).mockReturnValue(configs);
  vi.mocked(getDeletedTenantConfigs).mockReturnValue(deletedConfigs);

  const mockFactory = new ConfluenceAuthFactory();
  vi.mocked(mockFactory.createAuthStrategy).mockImplementation(() => createMockAuth());

  const mockApiClientFactory = new ConfluenceApiClientFactory({} as ServiceRegistry);
  vi.mocked(mockApiClientFactory.create).mockImplementation(() => ({}) as never);

  const mockUniqueApiFactory = {
    create: vi.fn().mockImplementation(() => createMockUniqueApiClient()),
  };

  const serviceRegistry = new ServiceRegistry();
  const registry = new TenantRegistry(
    mockFactory,
    mockApiClientFactory,
    mockUniqueApiFactory,
    serviceRegistry,
  );
  registry.onModuleInit();
  return { registry, serviceRegistry, mockUniqueApiFactory };
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

    it('logs tenant registration', () => {
      createRegistry([{ name: 'tenant-a', config: createMockTenantConfig() }]);

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Tenant registered' }),
      );
    });

    it('calls ConfluenceAuthFactory.createAuthStrategy for each tenant', () => {
      const configA = createMockTenantConfig();
      const configB = createMockTenantConfig();

      vi.mocked(getTenantConfigs).mockReturnValue([
        { name: 'tenant-a', config: configA },
        { name: 'tenant-b', config: configB },
      ]);

      const mockFactory = new ConfluenceAuthFactory();
      vi.mocked(mockFactory.createAuthStrategy).mockReturnValue(createMockAuth());

      const mockApiClientFactory = new ConfluenceApiClientFactory({} as ServiceRegistry);
      vi.mocked(mockApiClientFactory.create).mockReturnValue({} as never);

      const mockUniqueApiFactory = { create: vi.fn().mockReturnValue(createMockUniqueApiClient()) };

      const serviceRegistry = new ServiceRegistry();
      const registry = new TenantRegistry(
        mockFactory,
        mockApiClientFactory,
        mockUniqueApiFactory,
        serviceRegistry,
      );
      registry.onModuleInit();

      expect(mockFactory.createAuthStrategy).toHaveBeenCalledWith(configA.confluence);
      expect(mockFactory.createAuthStrategy).toHaveBeenCalledWith(configB.confluence);
    });

    it('calls uniqueApiFactory.create for each tenant with correct config', () => {
      const configA = createMockTenantConfig();
      const configB = createMockTenantConfig();

      const { mockUniqueApiFactory } = createRegistry([
        { name: 'tenant-a', config: configA },
        { name: 'tenant-b', config: configB },
      ]);

      expect(mockUniqueApiFactory.create).toHaveBeenCalledTimes(2);
      expect(mockUniqueApiFactory.create).toHaveBeenCalledWith(
        expect.objectContaining({
          auth: expect.objectContaining({
            serviceAuthMode: 'cluster_local',
            serviceId: 'confluence-connector',
          }),
          ingestion: expect.objectContaining({
            baseUrl: configA.unique.ingestionServiceBaseUrl,
          }),
          scopeManagement: expect.objectContaining({
            baseUrl: configA.unique.scopeManagementServiceBaseUrl,
          }),
          metadata: { clientName: 'confluence-connector', tenantKey: 'tenant-a' },
        }),
      );
    });

    it('calls ConfluenceApiClientFactory.create for each tenant', () => {
      const configA = createMockTenantConfig();
      const configB = createMockTenantConfig();

      vi.mocked(getTenantConfigs).mockReturnValue([
        { name: 'tenant-a', config: configA },
        { name: 'tenant-b', config: configB },
      ]);

      const mockFactory = new ConfluenceAuthFactory();
      vi.mocked(mockFactory.createAuthStrategy).mockReturnValue(createMockAuth());

      const mockApiClientFactory = new ConfluenceApiClientFactory({} as ServiceRegistry);
      vi.mocked(mockApiClientFactory.create).mockReturnValue({} as never);

      const mockUniqueApiFactory = { create: vi.fn().mockReturnValue(createMockUniqueApiClient()) };

      const serviceRegistry = new ServiceRegistry();
      const registry = new TenantRegistry(
        mockFactory,
        mockApiClientFactory,
        mockUniqueApiFactory,
        serviceRegistry,
      );
      registry.onModuleInit();

      expect(mockApiClientFactory.create).toHaveBeenCalledWith(configA.confluence);
      expect(mockApiClientFactory.create).toHaveBeenCalledWith(configB.confluence);
    });

    it('registers ConfluenceAuth, UniqueApiClient, and ConfluenceApiClient in ServiceRegistry for each tenant', () => {
      const configs: NamedTenantConfig[] = [{ name: 'tenant-a', config: createMockTenantConfig() }];

      const { registry, serviceRegistry } = createRegistry(configs);
      const tenant = registry.getTenant('tenant-a');

      tenantStorage.run(tenant, () => {
        expect(serviceRegistry.getService(ConfluenceAuth)).toBeDefined();
        expect(serviceRegistry.getService(UniqueApiClient)).toBeDefined();
        expect(serviceRegistry.getService(ConfluenceApiClient)).toBeDefined();
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

    it('throws for deleted tenant name', () => {
      const { registry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-tenant', config: createMockTenantConfig() }],
      );

      expect(() => registry.getTenant('deleted-tenant')).toThrow('Unknown tenant: deleted-tenant');
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

  describe('onModuleInit with deleted tenants', () => {
    it('registers deleted tenants with only UniqueApiClient', () => {
      const deletedConfigs: NamedTenantConfig[] = [
        { name: 'deleted-tenant', config: createMockTenantConfig() },
      ];

      const { serviceRegistry, mockUniqueApiFactory } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        deletedConfigs,
      );

      const deletedTenant = {
        name: 'deleted-tenant',
        config: deletedConfigs[0].config,
        isScanning: false,
      };
      tenantStorage.run(deletedTenant, () => {
        expect(serviceRegistry.getService(UniqueApiClient)).toBeDefined();
      });

      expect(mockUniqueApiFactory.create).toHaveBeenCalledTimes(2);
    });

    it('logs deleted tenant registration', () => {
      createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-tenant', config: createMockTenantConfig() }],
      );

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-tenant',
          msg: 'Deleted tenant registered for cleanup',
        }),
      );
    });

    it('does not include deleted tenants in tenantCount', () => {
      const { registry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-tenant', config: createMockTenantConfig() }],
      );

      expect(registry.tenantCount).toBe(1);
    });
  });

  describe('processDeletedTenants', () => {
    it('completes without errors when no deleted tenants exist', async () => {
      const { registry } = createRegistry([
        { name: 'active-tenant', config: createMockTenantConfig() },
      ]);

      await registry.processDeletedTenants();

      expect(mockLogger.error).not.toHaveBeenCalled();
    });

    it('delegates cleanup to TenantDeleteService for each deleted tenant', async () => {
      const deletedConfig = createMockTenantConfig();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-tenant', config: deletedConfig }],
      );

      const deletedTenant = { name: 'deleted-tenant', config: deletedConfig, isScanning: false };
      const cleanupService = tenantStorage.run(deletedTenant, () =>
        serviceRegistry.getService(TenantDeleteService),
      );
      const cleanupSpy = vi
        .spyOn(cleanupService, 'deleteTenantContent')
        .mockResolvedValue(undefined);

      await registry.processDeletedTenants();

      expect(cleanupSpy).toHaveBeenCalledOnce();
    });

    it('continues processing remaining tenants when one fails', async () => {
      const configA = createMockTenantConfig();
      const configB = createMockTenantConfig();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [
          { name: 'fail-tenant', config: configA },
          { name: 'ok-tenant', config: configB },
        ],
      );

      const failTenant = { name: 'fail-tenant', config: configA, isScanning: false };
      const failCleanup = tenantStorage.run(failTenant, () =>
        serviceRegistry.getService(TenantDeleteService),
      );
      vi.spyOn(failCleanup, 'deleteTenantContent').mockRejectedValue(new Error('API error'));

      const okTenant = { name: 'ok-tenant', config: configB, isScanning: false };
      const okCleanup = tenantStorage.run(okTenant, () =>
        serviceRegistry.getService(TenantDeleteService),
      );
      const okSpy = vi.spyOn(okCleanup, 'deleteTenantContent').mockResolvedValue(undefined);

      await registry.processDeletedTenants();

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'fail-tenant',
          msg: 'Tenant cleanup failed',
        }),
      );
      expect(okSpy).toHaveBeenCalledOnce();
    });

    it('registers TenantDeleteService for deleted tenants', () => {
      const deletedConfig = createMockTenantConfig();
      const { serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-tenant', config: deletedConfig }],
      );

      const deletedTenant = { name: 'deleted-tenant', config: deletedConfig, isScanning: false };
      const cleanupService = tenantStorage.run(deletedTenant, () =>
        serviceRegistry.getService(TenantDeleteService),
      );

      expect(cleanupService).toBeInstanceOf(TenantDeleteService);
    });
  });
});
