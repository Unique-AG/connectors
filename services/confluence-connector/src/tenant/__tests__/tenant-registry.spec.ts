import { UniqueApiClient } from '@unique-ag/unique-api';
import { describe, expect, it, vi } from 'vitest';
import { ConfluenceAuth, ConfluenceAuthFactory } from '../../auth/confluence-auth';
import type { NamedTenantConfig, TenantConfig } from '../../config/tenant-config-loader';
import { getDeletedTenantConfigs, getTenantConfigs } from '../../config/tenant-config-loader';
import { ConfluenceApiClient, ConfluenceApiClientFactory } from '../../confluence-api';
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
      getFileIdsByScope: vi.fn(),
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

function createMockTenantConfigWithV1(): TenantConfig {
  const config = createMockTenantConfig();
  return {
    ...config,
    ingestion: {
      ...config.ingestion,
      useV1KeyFormat: true,
    },
  } as unknown as TenantConfig;
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
    function getUniqueClientForTenant(
      serviceRegistry: ServiceRegistry,
      tenantName: string,
      config: TenantConfig,
    ): ReturnType<typeof createMockUniqueApiClient> {
      const tenant = { name: tenantName, config, isScanning: false };
      return tenantStorage.run(tenant, () => {
        return serviceRegistry.getService(UniqueApiClient) as unknown as ReturnType<
          typeof createMockUniqueApiClient
        >;
      });
    }

    it('completes without errors when no deleted tenants exist', async () => {
      const { registry } = createRegistry([
        { name: 'active-tenant', config: createMockTenantConfig() },
      ]);

      await registry.processDeletedTenants();

      expect(mockLogger.error).not.toHaveBeenCalled();
    });

    it('skips cleanup when root scope is not found', async () => {
      const deletedConfig = createMockTenantConfig();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-tenant', config: deletedConfig }],
      );

      const uniqueClient = getUniqueClientForTenant(
        serviceRegistry,
        'deleted-tenant',
        deletedConfig,
      );
      uniqueClient.scopes.getById.mockResolvedValue(null);

      await registry.processDeletedTenants();

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-tenant',
          msg: expect.stringContaining('not found, skipping'),
        }),
      );
      expect(uniqueClient.scopes.listChildren).not.toHaveBeenCalled();
    });

    it('skips cleanup when already cleaned up for V2 (no children, no files)', async () => {
      const deletedConfig = createMockTenantConfig();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-tenant', config: deletedConfig }],
      );

      const uniqueClient = getUniqueClientForTenant(
        serviceRegistry,
        'deleted-tenant',
        deletedConfig,
      );
      uniqueClient.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
      uniqueClient.scopes.listChildren.mockResolvedValue([]);
      uniqueClient.files.getCountByKeyPrefix.mockResolvedValue(0);

      await registry.processDeletedTenants();

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-tenant',
          msg: 'Already cleaned up, skipping',
        }),
      );
      expect(uniqueClient.files.deleteByKeyPrefix).not.toHaveBeenCalled();
    });

    it('skips cleanup when already cleaned up for V1 (no children)', async () => {
      const deletedConfig = createMockTenantConfigWithV1();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-v1', config: deletedConfig }],
      );

      const uniqueClient = getUniqueClientForTenant(serviceRegistry, 'deleted-v1', deletedConfig);
      uniqueClient.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
      uniqueClient.scopes.listChildren.mockResolvedValue([]);

      await registry.processDeletedTenants();

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-v1',
          msg: 'Already cleaned up, skipping',
        }),
      );
      expect(uniqueClient.files.getCountByKeyPrefix).not.toHaveBeenCalled();
      expect(uniqueClient.files.getFileIdsByScope).not.toHaveBeenCalled();
    });

    it('deletes files by key prefix and child scopes for V2 tenants', async () => {
      const deletedConfig = createMockTenantConfig();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-tenant', config: deletedConfig }],
      );

      const childScopes = [
        { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
        { id: 'child-2', name: 'space-b', parentId: 'scope-1', externalId: null },
      ];

      const uniqueClient = getUniqueClientForTenant(
        serviceRegistry,
        'deleted-tenant',
        deletedConfig,
      );
      uniqueClient.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
      uniqueClient.scopes.listChildren.mockResolvedValue(childScopes);
      uniqueClient.files.getCountByKeyPrefix.mockResolvedValue(5);
      uniqueClient.files.deleteByKeyPrefix.mockResolvedValue(5);
      uniqueClient.scopes.delete.mockResolvedValue({
        successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
        failedFolders: [],
      });

      await registry.processDeletedTenants();

      expect(uniqueClient.files.deleteByKeyPrefix).toHaveBeenCalledWith('deleted-tenant');
      expect(uniqueClient.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
      expect(uniqueClient.scopes.delete).toHaveBeenCalledWith('child-2', { recursive: true });
      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-tenant',
          msg: 'Tenant cleanup completed',
        }),
      );
    });

    it('deletes files by scope ownership for V1 tenants', async () => {
      const deletedConfig = createMockTenantConfigWithV1();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-v1', config: deletedConfig }],
      );

      const childScopes = [
        { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
      ];

      const uniqueClient = getUniqueClientForTenant(serviceRegistry, 'deleted-v1', deletedConfig);
      uniqueClient.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
      uniqueClient.scopes.listChildren.mockResolvedValue(childScopes);
      uniqueClient.files.getFileIdsByScope.mockResolvedValue(['file-1', 'file-2']);
      uniqueClient.files.deleteByIds.mockResolvedValue(2);
      uniqueClient.scopes.delete.mockResolvedValue({
        successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
        failedFolders: [],
      });

      await registry.processDeletedTenants();

      expect(uniqueClient.files.getFileIdsByScope).toHaveBeenCalledWith('child-1');
      expect(uniqueClient.files.deleteByIds).toHaveBeenCalledWith(['file-1', 'file-2']);
      expect(uniqueClient.files.deleteByKeyPrefix).not.toHaveBeenCalled();
      expect(uniqueClient.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-v1',
          msg: 'Tenant cleanup completed',
        }),
      );
    });

    it('skips file deletion for V1 scopes with no files', async () => {
      const deletedConfig = createMockTenantConfigWithV1();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-v1', config: deletedConfig }],
      );

      const childScopes = [
        { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
      ];

      const uniqueClient = getUniqueClientForTenant(serviceRegistry, 'deleted-v1', deletedConfig);
      uniqueClient.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
      uniqueClient.scopes.listChildren.mockResolvedValue(childScopes);
      uniqueClient.files.getFileIdsByScope.mockResolvedValue([]);
      uniqueClient.scopes.delete.mockResolvedValue({
        successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
        failedFolders: [],
      });

      await registry.processDeletedTenants();

      expect(uniqueClient.files.deleteByIds).not.toHaveBeenCalled();
      expect(uniqueClient.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
    });

    it('deletes files by scope ownership for V1 tenants with multiple child scopes', async () => {
      const deletedConfig = createMockTenantConfigWithV1();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-v1', config: deletedConfig }],
      );

      const childScopes = [
        { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
        { id: 'child-2', name: 'space-b', parentId: 'scope-1', externalId: null },
        { id: 'child-3', name: 'space-c', parentId: 'scope-1', externalId: null },
      ];

      const uniqueClient = getUniqueClientForTenant(serviceRegistry, 'deleted-v1', deletedConfig);
      uniqueClient.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
      uniqueClient.scopes.listChildren.mockResolvedValue(childScopes);
      uniqueClient.files.getFileIdsByScope
        .mockResolvedValueOnce(['file-1', 'file-2'])
        .mockResolvedValueOnce(['file-3'])
        .mockResolvedValueOnce([]);
      uniqueClient.files.deleteByIds.mockResolvedValue(2);
      uniqueClient.scopes.delete.mockResolvedValue({
        successFolders: [{ id: 'id', name: 'name', path: '/path' }],
        failedFolders: [],
      });

      await registry.processDeletedTenants();

      expect(uniqueClient.files.getFileIdsByScope).toHaveBeenCalledTimes(3);
      expect(uniqueClient.files.getFileIdsByScope).toHaveBeenCalledWith('child-1');
      expect(uniqueClient.files.getFileIdsByScope).toHaveBeenCalledWith('child-2');
      expect(uniqueClient.files.getFileIdsByScope).toHaveBeenCalledWith('child-3');
      expect(uniqueClient.files.deleteByIds).toHaveBeenCalledTimes(2);
      expect(uniqueClient.files.deleteByIds).toHaveBeenCalledWith(['file-1', 'file-2']);
      expect(uniqueClient.files.deleteByIds).toHaveBeenCalledWith(['file-3']);
      expect(uniqueClient.scopes.delete).toHaveBeenCalledTimes(3);
    });

    it('logs warning when scope deletion has failures', async () => {
      const deletedConfig = createMockTenantConfig();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-tenant', config: deletedConfig }],
      );

      const childScopes = [
        { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
      ];

      const uniqueClient = getUniqueClientForTenant(
        serviceRegistry,
        'deleted-tenant',
        deletedConfig,
      );
      uniqueClient.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
      uniqueClient.scopes.listChildren.mockResolvedValue(childScopes);
      uniqueClient.files.getCountByKeyPrefix.mockResolvedValue(5);
      uniqueClient.files.deleteByKeyPrefix.mockResolvedValue(5);
      uniqueClient.scopes.delete.mockResolvedValue({
        successFolders: [],
        failedFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      });

      await registry.processDeletedTenants();

      expect(mockLogger.warn).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-tenant',
          scopeName: 'space-a',
          msg: 'Partial scope deletion failure',
        }),
      );
      expect(mockLogger.warn).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-tenant',
          msg: 'Tenant cleanup completed with scope deletion failures',
        }),
      );
    });

    it('still proceeds with scope deletion when V2 has children but zero files', async () => {
      const deletedConfig = createMockTenantConfig();
      const { registry, serviceRegistry } = createRegistry(
        [{ name: 'active-tenant', config: createMockTenantConfig() }],
        [{ name: 'deleted-tenant', config: deletedConfig }],
      );

      const childScopes = [
        { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
      ];

      const uniqueClient = getUniqueClientForTenant(
        serviceRegistry,
        'deleted-tenant',
        deletedConfig,
      );
      uniqueClient.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
      uniqueClient.scopes.listChildren.mockResolvedValue(childScopes);
      uniqueClient.files.getCountByKeyPrefix.mockResolvedValue(0);
      uniqueClient.files.deleteByKeyPrefix.mockResolvedValue(0);
      uniqueClient.scopes.delete.mockResolvedValue({
        successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
        failedFolders: [],
      });

      await registry.processDeletedTenants();

      expect(uniqueClient.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-tenant',
          msg: 'Tenant cleanup completed',
        }),
      );
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

      const failClient = getUniqueClientForTenant(serviceRegistry, 'fail-tenant', configA);
      failClient.scopes.getById.mockRejectedValue(new Error('API error'));

      const okClient = getUniqueClientForTenant(serviceRegistry, 'ok-tenant', configB);
      okClient.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
      okClient.scopes.listChildren.mockResolvedValue([]);
      okClient.files.getCountByKeyPrefix.mockResolvedValue(0);

      await registry.processDeletedTenants();

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'fail-tenant',
          msg: 'Tenant cleanup failed',
        }),
      );
      expect(okClient.scopes.getById).toHaveBeenCalled();
    });
  });
});
