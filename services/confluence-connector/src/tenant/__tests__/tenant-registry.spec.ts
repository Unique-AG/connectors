import { UniqueApiClient } from '@unique-ag/unique-api';
import { createMock } from '@golevelup/ts-vitest';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConfluenceAuth, ConfluenceAuthFactory } from '../../auth/confluence-auth';
import type { NamedTenantConfig, TenantConfig } from '../../config/tenant-config-loader';
import { getDeletedTenantConfigs, getTenantConfigs } from '../../config/tenant-config-loader';
import { ConfluenceApiClient, ConfluenceApiClientFactory } from '../../confluence-api';
import { createNoopMetrics } from '../../metrics/__mocks__/noop-metrics';
import type { ProxyService } from '../../proxy';
import { ServiceRegistry } from '../service-registry';
import { tenantStorage } from '../tenant-context.storage';
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

const mockProxyService = createMock<ProxyService>();

function createMockTenantConfig(): TenantConfig {
  return createMock<TenantConfig>({
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
      attachments: { enabled: false, allowedExtensions: [], maxFileSizeMb: 10 },
    },
    processing: {},
  });
}

function createMockAuth(): ConfluenceAuth {
  return { acquireToken: vi.fn().mockResolvedValue('mock-token') };
}

function createMockUniqueApiClient() {
  return {
    auth: {},
    scopes: {},
    files: { getByKeys: vi.fn(), getByKeyPrefix: vi.fn(), delete: vi.fn(), deleteByIds: vi.fn() },
    users: {},
    groups: {},
    ingestion: { performFileDiff: vi.fn(), registerContent: vi.fn(), finalizeIngestion: vi.fn() },
    close: vi.fn(),
  };
}

function createRegistry(configs: NamedTenantConfig[]): {
  registry: TenantRegistry;
  serviceRegistry: ServiceRegistry;
  mockUniqueApiFactory: { create: ReturnType<typeof vi.fn> };
} {
  vi.mocked(getTenantConfigs).mockReturnValue(configs);

  const mockFactory = new ConfluenceAuthFactory(mockProxyService);
  vi.mocked(mockFactory.createAuthStrategy).mockImplementation(() => createMockAuth());

  const mockApiClientFactory = new ConfluenceApiClientFactory(
    {} as ServiceRegistry,
    mockProxyService,
  );
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
    mockProxyService,
    createNoopMetrics(),
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

      const mockFactory = new ConfluenceAuthFactory(mockProxyService);
      vi.mocked(mockFactory.createAuthStrategy).mockReturnValue(createMockAuth());

      const mockApiClientFactory = new ConfluenceApiClientFactory(
        {} as ServiceRegistry,
        mockProxyService,
      );
      vi.mocked(mockApiClientFactory.create).mockReturnValue({} as never);

      const mockUniqueApiFactory = { create: vi.fn().mockReturnValue(createMockUniqueApiClient()) };

      const serviceRegistry = new ServiceRegistry();
      const registry = new TenantRegistry(
        mockFactory,
        mockApiClientFactory,
        mockUniqueApiFactory,
        serviceRegistry,
        mockProxyService,
        createNoopMetrics(),
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

      const mockFactory = new ConfluenceAuthFactory(mockProxyService);
      vi.mocked(mockFactory.createAuthStrategy).mockReturnValue(createMockAuth());

      const mockApiClientFactory = new ConfluenceApiClientFactory(
        {} as ServiceRegistry,
        mockProxyService,
      );
      vi.mocked(mockApiClientFactory.create).mockReturnValue({} as never);

      const mockUniqueApiFactory = { create: vi.fn().mockReturnValue(createMockUniqueApiClient()) };

      const serviceRegistry = new ServiceRegistry();
      const registry = new TenantRegistry(
        mockFactory,
        mockApiClientFactory,
        mockUniqueApiFactory,
        serviceRegistry,
        mockProxyService,
        createNoopMetrics(),
      );
      registry.onModuleInit();

      expect(mockApiClientFactory.create).toHaveBeenCalledWith(
        configA.confluence,
        { attachmentsEnabled: false },
        expect.anything(),
      );
      expect(mockApiClientFactory.create).toHaveBeenCalledWith(
        configB.confluence,
        { attachmentsEnabled: false },
        expect.anything(),
      );
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
      vi.mocked(getDeletedTenantConfigs).mockReturnValue([
        { name: 'deleted-tenant', config: createMockTenantConfig() },
      ]);

      const { registry } = createRegistry([
        { name: 'active-tenant', config: createMockTenantConfig() },
      ]);

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

    it('does not include deleted tenants', () => {
      vi.mocked(getDeletedTenantConfigs).mockReturnValue([
        { name: 'deleted-tenant', config: createMockTenantConfig() },
      ]);

      const { registry } = createRegistry([
        { name: 'active-tenant', config: createMockTenantConfig() },
      ]);

      const all = registry.getAllTenants();
      expect(all).toHaveLength(1);
      expect(all[0]?.name).toBe('active-tenant');
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
    afterEach(() => {
      vi.mocked(getDeletedTenantConfigs).mockReturnValue([]);
    });

    it('registers UniqueApiClient for deleted tenants', () => {
      const deletedConfig = createMockTenantConfig();
      vi.mocked(getDeletedTenantConfigs).mockReturnValue([
        { name: 'deleted-tenant', config: deletedConfig },
      ]);

      const { serviceRegistry } = createRegistry([
        { name: 'active-tenant', config: createMockTenantConfig() },
      ]);

      const deletedTenantContext = {
        name: 'deleted-tenant',
        config: deletedConfig,
        isScanning: false,
      };
      tenantStorage.run(deletedTenantContext, () => {
        expect(serviceRegistry.getService(UniqueApiClient)).toBeDefined();
      });
    });

    it('logs registration of deleted tenants', () => {
      vi.mocked(getDeletedTenantConfigs).mockReturnValue([
        { name: 'deleted-tenant', config: createMockTenantConfig() },
      ]);

      createRegistry([{ name: 'active-tenant', config: createMockTenantConfig() }]);

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-tenant',
          msg: 'Deleted tenant registered for cleanup',
        }),
      );
    });

    it('does not include deleted tenants in tenantCount', () => {
      vi.mocked(getDeletedTenantConfigs).mockReturnValue([
        { name: 'deleted-tenant', config: createMockTenantConfig() },
      ]);

      const { registry } = createRegistry([
        { name: 'active-tenant', config: createMockTenantConfig() },
      ]);

      expect(registry.tenantCount).toBe(1);
    });
  });

  describe('getDeletedTenants', () => {
    it('returns empty array when no deleted tenants exist', () => {
      vi.mocked(getDeletedTenantConfigs).mockReturnValue([]);

      const { registry } = createRegistry([
        { name: 'active-tenant', config: createMockTenantConfig() },
      ]);

      expect(registry.getDeletedTenants()).toEqual([]);
    });

    it('returns deleted tenant contexts', () => {
      const deletedConfig = createMockTenantConfig();
      vi.mocked(getDeletedTenantConfigs).mockReturnValue([
        { name: 'deleted-tenant', config: deletedConfig },
      ]);

      const { registry } = createRegistry([
        { name: 'active-tenant', config: createMockTenantConfig() },
      ]);

      const deleted = registry.getDeletedTenants();
      expect(deleted).toHaveLength(1);
      expect(deleted[0]?.name).toBe('deleted-tenant');
      expect(deleted[0]?.config).toBe(deletedConfig);
    });
  });
});
