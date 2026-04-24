import { SchedulerRegistry } from '@nestjs/schedule';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TenantStatus } from '../../config';
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
    status: 'active',
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

function createMockTenantRegistry(tenants: TenantContext[]): TenantRegistry {
  return {
    getAllTenants: vi.fn().mockReturnValue(tenants),
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
    if (tenant.status === TenantStatus.Deleted) {
      serviceRegistry.register(
        tenant.name,
        TenantDeleteService,
        createMockDeleteService() as unknown as TenantDeleteService,
      );
    } else {
      serviceRegistry.register(
        tenant.name,
        ConfluenceSynchronizationService,
        createMockSyncService() as unknown as ConfluenceSynchronizationService,
      );
    }
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

    it('triggers initial job for each tenant', async () => {
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
            msg: 'Scheduled job with cron: */5 * * * *',
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

    it('registers cron jobs for deleted tenants', async () => {
      const deletedTenant = createMockTenant('deleted-tenant', { status: 'deleted' });
      tenantRegistry = createMockTenantRegistry([tenantA, deletedTenant]);
      serviceRegistry = createMockServiceRegistry([tenantA, deletedTenant]);
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      scheduler.onModuleInit();

      await vi.waitFor(() => {
        expect(schedulerRegistry.addCronJob).toHaveBeenCalledTimes(2);
        expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith(
          'sync:deleted-tenant',
          expect.anything(),
        );
      });
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
    it('calls synchronize() for active tenants', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      expect(syncService.synchronize).toHaveBeenCalledOnce();
    });

    it('calls deleteTenantContent() for deleted tenants', async () => {
      const deletedTenant = createMockTenant('deleted-tenant', { status: 'deleted' });
      tenantRegistry = createMockTenantRegistry([deletedTenant]);
      serviceRegistry = createMockServiceRegistry([deletedTenant]);
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(deletedTenant);

      const deleteService = tenantStorage.run(deletedTenant, () =>
        serviceRegistry.getService(TenantDeleteService),
      );
      expect(deleteService.deleteTenantContent).toHaveBeenCalledOnce();
    });

    it('catches and logs cleanup errors with tenant name', async () => {
      const deletedTenant = createMockTenant('deleted-tenant', { status: 'deleted' });
      tenantRegistry = createMockTenantRegistry([deletedTenant]);
      serviceRegistry = createMockServiceRegistry([deletedTenant]);
      scheduler = new TenantSyncScheduler(tenantRegistry, serviceRegistry, schedulerRegistry);

      const deleteService = tenantStorage.run(deletedTenant, () =>
        serviceRegistry.getService(TenantDeleteService),
      );
      vi.mocked(deleteService.deleteTenantContent).mockRejectedValue(new Error('cleanup exploded'));

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(deletedTenant);

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'deleted-tenant',
          err: expect.any(Error),
          msg: 'Unexpected error in tenant job',
        }),
      );
    });

    it('skips job when shutting down', async () => {
      scheduler.onModuleDestroy();

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockLogger.log).toHaveBeenCalledWith({ msg: 'Skipping job due to shutdown' });
      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      expect(syncService.synchronize).not.toHaveBeenCalled();
    });

    it('catches and logs sync errors with tenant name', async () => {
      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      vi.mocked(syncService.synchronize).mockRejectedValue(new Error('unexpected failure'));

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'tenant-a',
          err: expect.any(Error),
          msg: 'Unexpected error in tenant job',
        }),
      );
    });
  });
});
