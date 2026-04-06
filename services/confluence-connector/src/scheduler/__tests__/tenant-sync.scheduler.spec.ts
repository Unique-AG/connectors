import { UniqueApiClient } from '@unique-ag/unique-api';
import { SchedulerRegistry } from '@nestjs/schedule';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfluenceSynchronizationService } from '../../synchronization/confluence-synchronization.service';
import { ServiceRegistry } from '../../tenant/service-registry';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import { TenantRegistry } from '../../tenant/tenant-registry';
import { TenantSyncScheduler } from '../tenant-sync.scheduler';

const mockLogger = vi.hoisted(() => ({
  log: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
  verbose: vi.fn(),
}));

vi.mock('@nestjs/common', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nestjs/common')>();
  return {
    ...actual,
    Logger: vi.fn().mockImplementation(() => mockLogger),
  };
});

function createMockSyncService() {
  return { synchronize: vi.fn().mockResolvedValue(undefined) };
}

function createMockUniqueApiClient() {
  return {
    scopes: {
      getById: vi.fn().mockResolvedValue(null),
      listChildren: vi.fn().mockResolvedValue([]),
      delete: vi.fn().mockResolvedValue({ successFolders: [], failedFolders: [] }),
    },
    files: {
      getCountByKeyPrefix: vi.fn().mockResolvedValue(0),
      getByKeyPrefix: vi.fn().mockResolvedValue([]),
      deleteByKeyPrefix: vi.fn().mockResolvedValue(0),
      deleteByIds: vi.fn().mockResolvedValue(0),
    },
  };
}

function createDeletedTenant(
  name: string,
  overrides: { useV1KeyFormat?: boolean; scopeId?: string } = {},
): TenantContext {
  return {
    name,
    config: {
      processing: { scanIntervalCron: '*/5 * * * *' },
      ingestion: {
        scopeId: overrides.scopeId ?? 'deleted-scope-id',
        useV1KeyFormat: overrides.useV1KeyFormat ?? false,
      },
    },
    isScanning: false,
  } as unknown as TenantContext;
}

function createMockTenant(name: string, overrides: Partial<TenantContext> = {}): TenantContext {
  return {
    name,
    config: {
      processing: { scanIntervalCron: '*/5 * * * *' },
    },
    ...overrides,
  } as unknown as TenantContext;
}

function createMockSchedulerRegistry(): SchedulerRegistry {
  const jobs = new Map<string, { stop: ReturnType<typeof vi.fn> }>();
  return {
    addCronJob: vi.fn((name: string, job: unknown) => {
      jobs.set(name, job as { stop: ReturnType<typeof vi.fn> });
    }),
    getCronJobs: vi.fn(() => jobs),
  } as unknown as SchedulerRegistry;
}

function createMockTenantRegistry(
  tenants: TenantContext[],
  deletedTenants: TenantContext[] = [],
): TenantRegistry {
  return {
    getAllTenants: vi.fn().mockReturnValue(tenants),
    getDeletedTenants: vi.fn().mockReturnValue(deletedTenants),
    tenantCount: tenants.length,
    run: vi
      .fn()
      .mockImplementation(
        <R>(tenant: TenantContext, fn: () => R): R => tenantStorage.run(tenant, fn),
      ),
  } as unknown as TenantRegistry;
}

function createMockServiceRegistry(tenants: TenantContext[]): ServiceRegistry {
  const serviceRegistry = new ServiceRegistry();
  for (const tenant of tenants) {
    serviceRegistry.register(
      tenant.name,
      ConfluenceSynchronizationService,
      createMockSyncService() as unknown as ConfluenceSynchronizationService,
    );
  }
  return serviceRegistry;
}

describe('TenantSyncScheduler', () => {
  let scheduler: TenantSyncScheduler;
  let tenantRegistry: TenantRegistry;
  let serviceRegistry: ServiceRegistry;
  let schedulerRegistry: SchedulerRegistry;
  let tenantA: TenantContext;
  let tenantB: TenantContext;

  beforeEach(() => {
    vi.clearAllMocks();
    tenantA = createMockTenant('tenant-a');
    tenantB = createMockTenant('tenant-b');

    tenantRegistry = createMockTenantRegistry([tenantA, tenantB]);
    serviceRegistry = createMockServiceRegistry([tenantA, tenantB]);
    schedulerRegistry = createMockSchedulerRegistry();
    scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);
  });

  describe('onModuleInit', () => {
    it('registers a cron job per tenant', () => {
      scheduler.onModuleInit();

      expect(schedulerRegistry.addCronJob).toHaveBeenCalledTimes(2);
      expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith('sync:tenant-a', expect.anything());
      expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith('sync:tenant-b', expect.anything());
    });

    it('triggers initial sync for each tenant', async () => {
      scheduler.onModuleInit();

      await vi.waitFor(() => {
        const syncA = tenantStorage.run(tenantA, () =>
          serviceRegistry.getService(ConfluenceSynchronizationService),
        );
        expect(syncA.synchronize).toHaveBeenCalledOnce();
        const syncB = tenantStorage.run(tenantB, () =>
          serviceRegistry.getService(ConfluenceSynchronizationService),
        );
        expect(syncB.synchronize).toHaveBeenCalledOnce();
      });
    });

    it('logs the scheduled cron expression', () => {
      scheduler.onModuleInit();

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'tenant-a',
          msg: 'Scheduled sync with cron: */5 * * * *',
        }),
      );
    });

    it('skips scheduling when no tenants are registered', () => {
      const emptyRegistry = createMockTenantRegistry([]);
      const emptyServiceRegistry = createMockServiceRegistry([]);
      const emptyScheduler = new TenantSyncScheduler(
        emptyRegistry,
        emptyServiceRegistry,
        schedulerRegistry,
      );

      emptyScheduler.onModuleInit();

      expect(emptyRegistry.getAllTenants).not.toHaveBeenCalled();
      expect(schedulerRegistry.addCronJob).not.toHaveBeenCalled();
    });
  });

  describe('onModuleDestroy', () => {
    it('stops all registered cron jobs', () => {
      scheduler.onModuleInit();
      const jobs = schedulerRegistry.getCronJobs();
      const stopSpies = [...jobs.values()].map((job) => vi.spyOn(job, 'stop'));

      scheduler.onModuleDestroy();

      for (const spy of stopSpies) {
        expect(spy).toHaveBeenCalled();
      }
    });
  });

  describe('syncTenant', () => {
    it('delegates to ConfluenceSynchronizationService.synchronize()', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      expect(syncService.synchronize).toHaveBeenCalledOnce();
    });

    it('skips sync when shutting down', async () => {
      scheduler.onModuleDestroy();

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockLogger.log).toHaveBeenCalledWith({ msg: 'Skipping sync due to shutdown' });
      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      expect(syncService.synchronize).not.toHaveBeenCalled();
      expect(tenantRegistry.getDeletedTenants).not.toHaveBeenCalled();
    });

    it('logs unexpected errors from synchronize()', async () => {
      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      vi.mocked(syncService.synchronize).mockRejectedValue(new Error('unexpected failure'));

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ err: expect.any(Error), msg: 'Unexpected sync error' }),
      );
    });

    it('processes deleted tenants before syncing active tenant', async () => {
      const deletedTenant = createDeletedTenant('deleted-a');
      const mockUniqueClient = createMockUniqueApiClient();
      mockUniqueClient.scopes.getById.mockResolvedValue({
        id: 'deleted-scope-id',
        name: 'root',
        parentId: null,
        externalId: null,
      });
      mockUniqueClient.scopes.listChildren.mockResolvedValue([
        { id: 'child-1', name: 'space1', parentId: 'deleted-scope-id', externalId: null },
      ]);
      mockUniqueClient.files.deleteByKeyPrefix.mockResolvedValue(5);

      tenantRegistry = createMockTenantRegistry([tenantA, tenantB], [deletedTenant]);
      serviceRegistry = createMockServiceRegistry([tenantA, tenantB]);
      serviceRegistry.register(
        deletedTenant.name,
        UniqueApiClient,
        mockUniqueClient as unknown as UniqueApiClient,
      );
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(tenantRegistry.getDeletedTenants).toHaveBeenCalled();
      expect(mockUniqueClient.scopes.getById).toHaveBeenCalledWith('deleted-scope-id');
      expect(mockUniqueClient.files.deleteByKeyPrefix).toHaveBeenCalledWith('deleted-a');
      expect(mockUniqueClient.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });

      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      expect(syncService.synchronize).toHaveBeenCalledOnce();
    });

    it('still syncs active tenant when cleanup of deleted tenant fails', async () => {
      const deletedTenant = createDeletedTenant('deleted-a');
      const mockUniqueClient = createMockUniqueApiClient();
      mockUniqueClient.scopes.getById.mockRejectedValue(new Error('API down'));

      tenantRegistry = createMockTenantRegistry([tenantA, tenantB], [deletedTenant]);
      serviceRegistry = createMockServiceRegistry([tenantA, tenantB]);
      serviceRegistry.register(
        deletedTenant.name,
        UniqueApiClient,
        mockUniqueClient as unknown as UniqueApiClient,
      );
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-a',
          msg: 'Cleanup failed, will retry on next cycle',
        }),
      );

      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      expect(syncService.synchronize).toHaveBeenCalledOnce();
    });

    it('skips cleanup when root scope is not found', async () => {
      const deletedTenant = createDeletedTenant('deleted-a');
      const mockUniqueClient = createMockUniqueApiClient();
      mockUniqueClient.scopes.getById.mockResolvedValue(null);

      tenantRegistry = createMockTenantRegistry([tenantA], [deletedTenant]);
      serviceRegistry = createMockServiceRegistry([tenantA]);
      serviceRegistry.register(
        deletedTenant.name,
        UniqueApiClient,
        mockUniqueClient as unknown as UniqueApiClient,
      );
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-a',
          msg: 'Root scope deleted-scope-id not found, skipping',
        }),
      );
      expect(mockUniqueClient.scopes.listChildren).not.toHaveBeenCalled();
    });

    it('skips cleanup when tenant is already cleaned up (V2)', async () => {
      const deletedTenant = createDeletedTenant('deleted-a');
      const mockUniqueClient = createMockUniqueApiClient();
      mockUniqueClient.scopes.getById.mockResolvedValue({
        id: 'deleted-scope-id',
        name: 'root',
        parentId: null,
        externalId: null,
      });
      mockUniqueClient.scopes.listChildren.mockResolvedValue([]);
      mockUniqueClient.files.getCountByKeyPrefix.mockResolvedValue(0);

      tenantRegistry = createMockTenantRegistry([tenantA], [deletedTenant]);
      serviceRegistry = createMockServiceRegistry([tenantA]);
      serviceRegistry.register(
        deletedTenant.name,
        UniqueApiClient,
        mockUniqueClient as unknown as UniqueApiClient,
      );
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-a',
          msg: 'Already cleaned up, skipping',
        }),
      );
      expect(mockUniqueClient.files.deleteByKeyPrefix).not.toHaveBeenCalled();
    });

    it('continues cleaning up remaining tenants when one fails', async () => {
      const failTenant = createDeletedTenant('fail-tenant');
      const okTenant = createDeletedTenant('ok-tenant');
      const failClient = createMockUniqueApiClient();
      failClient.scopes.getById.mockRejectedValue(new Error('API down'));
      const okClient = createMockUniqueApiClient();
      okClient.scopes.getById.mockResolvedValue({ id: 'ok-scope', name: 'root' });
      okClient.scopes.listChildren.mockResolvedValue([]);
      okClient.files.getCountByKeyPrefix.mockResolvedValue(0);

      tenantRegistry = createMockTenantRegistry([tenantA], [failTenant, okTenant]);
      serviceRegistry = createMockServiceRegistry([tenantA]);
      serviceRegistry.register(
        failTenant.name,
        UniqueApiClient,
        failClient as unknown as UniqueApiClient,
      );
      serviceRegistry.register(
        okTenant.name,
        UniqueApiClient,
        okClient as unknown as UniqueApiClient,
      );
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'fail-tenant',
          msg: 'Cleanup failed, will retry on next cycle',
        }),
      );
      expect(okClient.scopes.getById).toHaveBeenCalled();
    });

    it('uses deleteByIds for V1 key format tenants', async () => {
      const deletedTenant = createDeletedTenant('deleted-v1', { useV1KeyFormat: true });
      const mockUniqueClient = createMockUniqueApiClient();
      mockUniqueClient.scopes.getById.mockResolvedValue({
        id: 'deleted-scope-id',
        name: 'root',
        parentId: null,
        externalId: null,
      });
      mockUniqueClient.scopes.listChildren.mockResolvedValue([
        { id: 'child-1', name: 'space1', parentId: 'deleted-scope-id', externalId: 'confc:x:y' },
      ]);
      mockUniqueClient.files.getByKeyPrefix.mockResolvedValue([
        { id: 'file-1', key: 'k1' },
        { id: 'file-2', key: 'k2' },
      ]);

      tenantRegistry = createMockTenantRegistry([tenantA], [deletedTenant]);
      serviceRegistry = createMockServiceRegistry([tenantA]);
      serviceRegistry.register(
        deletedTenant.name,
        UniqueApiClient,
        mockUniqueClient as unknown as UniqueApiClient,
      );
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockUniqueClient.files.getByKeyPrefix).toHaveBeenCalledWith('confc:x:y');
      expect(mockUniqueClient.files.deleteByIds).toHaveBeenCalledWith(['file-1', 'file-2']);
      expect(mockUniqueClient.files.deleteByKeyPrefix).not.toHaveBeenCalled();
      expect(mockUniqueClient.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
    });
  });
});
