import { SchedulerRegistry } from '@nestjs/schedule';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfluenceSynchronizationService } from '../../synchronization/confluence-synchronization.service';
import { ServiceRegistry } from '../../tenant/service-registry';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import { TenantDeleteService } from '../../tenant/tenant-delete.service';
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

function createMockDeleteService() {
  return { deleteTenantContent: vi.fn().mockResolvedValue(undefined) };
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

function createMockServiceRegistry(
  tenants: TenantContext[],
  deletedTenants: TenantContext[] = [],
): ServiceRegistry {
  const serviceRegistry = new ServiceRegistry();
  for (const tenant of tenants) {
    serviceRegistry.register(
      tenant.name,
      ConfluenceSynchronizationService,
      createMockSyncService() as unknown as ConfluenceSynchronizationService,
    );
  }
  for (const tenant of deletedTenants) {
    serviceRegistry.register(
      tenant.name,
      TenantDeleteService,
      createMockDeleteService() as unknown as TenantDeleteService,
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
    it('registers a cron job per tenant', async () => {
      scheduler.onModuleInit();

      await vi.waitFor(() => {
        expect(schedulerRegistry.addCronJob).toHaveBeenCalledTimes(2);
        expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith(
          'sync:tenant-a',
          expect.anything(),
        );
        expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith(
          'sync:tenant-b',
          expect.anything(),
        );
      });
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

    it('logs the scheduled cron expression', async () => {
      scheduler.onModuleInit();

      await vi.waitFor(() => {
        expect(mockLogger.log).toHaveBeenCalledWith(
          expect.objectContaining({
            tenantName: 'tenant-a',
            msg: 'Scheduled sync with cron: */5 * * * *',
          }),
        );
      });
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
    it('processes deleted tenants before syncing', async () => {
      const deletedTenant = createMockTenant('deleted-tenant');
      tenantRegistry = createMockTenantRegistry([tenantA, tenantB], [deletedTenant]);
      serviceRegistry = createMockServiceRegistry([tenantA, tenantB], [deletedTenant]);
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      const deleteService = tenantStorage.run(deletedTenant, () =>
        serviceRegistry.getService(TenantDeleteService),
      );
      expect(deleteService.deleteTenantContent).toHaveBeenCalledOnce();
      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      expect(syncService.synchronize).toHaveBeenCalledOnce();
    });

    it('still syncs when tenant cleanup fails', async () => {
      const deletedTenant = createMockTenant('deleted-tenant');
      tenantRegistry = createMockTenantRegistry([tenantA, tenantB], [deletedTenant]);
      serviceRegistry = createMockServiceRegistry([tenantA, tenantB], [deletedTenant]);
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      const deleteService = tenantStorage.run(deletedTenant, () =>
        serviceRegistry.getService(TenantDeleteService),
      );
      vi.mocked(deleteService.deleteTenantContent).mockRejectedValue(
        new Error('cleanup exploded'),
      );

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Tenant cleanup failed' }),
      );
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
      expect(tenantRegistry.getDeletedTenants).not.toHaveBeenCalled();
      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      expect(syncService.synchronize).not.toHaveBeenCalled();
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
  });
});
