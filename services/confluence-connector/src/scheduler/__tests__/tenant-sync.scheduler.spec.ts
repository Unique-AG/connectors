import { createMock, type DeepMocked } from '@golevelup/ts-vitest';
import { SchedulerRegistry } from '@nestjs/schedule';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type TenantConfig, TenantStatus, UniqueAuthMode } from '../../config';
import { AuthMode } from '../../config/confluence.schema';
import { SyncStatusStore } from '../../health/sync-status.store';
import { ConfluenceSynchronizationService } from '../../synchronization/confluence-synchronization.service';
import { ServiceRegistry } from '../../tenant/service-registry';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import { TenantDeleteService } from '../../tenant/tenant-delete.service';
import { TenantRegistry } from '../../tenant/tenant-registry';
import { Redacted } from '../../utils/redacted';
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

const tenantConfig = {
  confluence: {
    instanceType: 'cloud',
    baseUrl: 'https://tenant.atlassian.net',
    cloudId: 'cloud-id',
    apiRateLimitPerMinute: 100,
    ingestSingleLabel: 'ai-ingest',
    ingestAllLabel: 'ai-ingest-all',
    auth: {
      mode: AuthMode.OAuth2Lo,
      clientId: 'client-id',
      clientSecret: new Redacted('client-secret'),
    },
  },
  unique: {
    serviceAuthMode: UniqueAuthMode.ClusterLocal,
    serviceExtraHeaders: { 'x-company-id': 'company-id', 'x-user-id': 'user-id' },
    ingestionServiceBaseUrl: 'http://ingestion.local:8091',
    scopeManagementServiceBaseUrl: 'http://scope-management.local:8094',
    apiRateLimitPerMinute: 100,
  },
  processing: { scanIntervalCron: '*/5 * * * *', concurrency: 1 },
  ingestion: {
    ingestionMode: 'flat',
    scopeId: 'scope-id',
    storeInternally: true,
    useV1KeyFormat: false,
    attachments: {
      enabled: true,
      allowedMimeTypes: ['application/pdf'],
      imageOcrEnabled: false,
      inlineImagesEnabled: true,
      maxFileSizeMb: 200,
    },
  },
} satisfies TenantConfig;

function createMockSyncService(): DeepMocked<ConfluenceSynchronizationService> {
  return createMock<ConfluenceSynchronizationService>({
    synchronize: vi.fn().mockResolvedValue({ status: 'success' }),
  });
}

function createMockDeleteService(): DeepMocked<TenantDeleteService> {
  return createMock<TenantDeleteService>({
    deleteTenantContent: vi.fn().mockResolvedValue({ status: 'success' }),
  });
}

function createTestTenant(name: string, overrides: Partial<TenantContext> = {}): TenantContext {
  return {
    name,
    status: TenantStatus.Active,
    config: tenantConfig,
    isScanning: false,
    ...overrides,
  } satisfies TenantContext;
}

function createMockSchedulerRegistry(): DeepMocked<SchedulerRegistry> {
  const jobs: ReturnType<SchedulerRegistry['getCronJobs']> = new Map();
  return createMock<SchedulerRegistry>({
    addCronJob: vi.fn((name: string, job: Parameters<SchedulerRegistry['addCronJob']>[1]) => {
      jobs.set(name, job);
    }),
    getCronJobs: vi.fn(() => jobs),
  });
}

function createMockTenantRegistry(tenants: TenantContext[]): DeepMocked<TenantRegistry> {
  return createMock<TenantRegistry>({
    getAllTenants: vi.fn().mockReturnValue(tenants),
    tenantCount: tenants.length,
    run: vi
      .fn()
      .mockImplementation(
        <R>(tenant: TenantContext, fn: () => R): R => tenantStorage.run(tenant, fn),
      ),
  });
}

function createMockServiceRegistry(tenants: TenantContext[]): ServiceRegistry {
  const serviceRegistry = new ServiceRegistry();
  for (const tenant of tenants) {
    if (tenant.status === TenantStatus.Deleted) {
      serviceRegistry.register(tenant.name, TenantDeleteService, createMockDeleteService());
    } else {
      serviceRegistry.register(
        tenant.name,
        ConfluenceSynchronizationService,
        createMockSyncService(),
      );
    }
  }
  return serviceRegistry;
}

describe('TenantSyncScheduler', () => {
  let scheduler: TenantSyncScheduler;
  let tenantRegistry: DeepMocked<TenantRegistry>;
  let serviceRegistry: ServiceRegistry;
  let schedulerRegistry: DeepMocked<SchedulerRegistry>;
  let syncStatusStore: DeepMocked<SyncStatusStore>;
  let tenantA: TenantContext;
  let tenantB: TenantContext;

  async function buildScheduler(tenants: TenantContext[]): Promise<void> {
    tenantRegistry = createMockTenantRegistry(tenants);
    serviceRegistry = createMockServiceRegistry(tenants);
    schedulerRegistry = createMockSchedulerRegistry();
    syncStatusStore = createMock<SyncStatusStore>();

    const { unit } = await TestBed.solitary(TenantSyncScheduler)
      .mock(TenantRegistry)
      .final(tenantRegistry)
      .mock(ServiceRegistry)
      .final(serviceRegistry)
      .mock(SchedulerRegistry)
      .final(schedulerRegistry)
      .mock(SyncStatusStore)
      .final(syncStatusStore)
      .compile();

    scheduler = unit;
  }

  beforeEach(async () => {
    vi.clearAllMocks();
    tenantA = createTestTenant('tenant-a');
    tenantB = createTestTenant('tenant-b');

    await buildScheduler([tenantA, tenantB]);
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

    it('skips scheduling when no tenants are registered', async () => {
      await buildScheduler([]);

      scheduler.onModuleInit();

      expect(tenantRegistry.getAllTenants).not.toHaveBeenCalled();
      expect(schedulerRegistry.addCronJob).not.toHaveBeenCalled();
    });

    it('registers cron jobs for deleted tenants', async () => {
      const deletedTenant = createTestTenant('deleted-tenant', { status: TenantStatus.Deleted });
      await buildScheduler([tenantA, deletedTenant]);

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
      const deletedTenant = createTestTenant('deleted-tenant', { status: TenantStatus.Deleted });
      await buildScheduler([deletedTenant]);

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(deletedTenant);

      const deleteService = tenantStorage.run(deletedTenant, () =>
        serviceRegistry.getService(TenantDeleteService),
      );
      expect(deleteService.deleteTenantContent).toHaveBeenCalledOnce();
    });

    it('catches and logs cleanup errors without recording sync health', async () => {
      const deletedTenant = createTestTenant('deleted-tenant', { status: TenantStatus.Deleted });
      await buildScheduler([deletedTenant]);

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
          msg: 'Unexpected error in tenant cleanup job',
        }),
      );
      expect(syncStatusStore.record).not.toHaveBeenCalled();
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

    it('records the sync result in the status store on success', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(syncStatusStore.record).toHaveBeenCalledOnce();
      expect(syncStatusStore.record).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'tenant-a',
          result: { status: 'success' },
        }),
      );
    });

    it('records a failure when synchronize() throws', async () => {
      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      vi.mocked(syncService.synchronize).mockRejectedValue(new Error('unexpected failure'));

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(syncStatusStore.record).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantName: 'tenant-a',
          result: { status: 'failure' },
        }),
      );
    });

    it('does not record sync_in_progress skips so they do not dilute the window', async () => {
      const syncService = tenantStorage.run(tenantA, () =>
        serviceRegistry.getService(ConfluenceSynchronizationService),
      );
      vi.mocked(syncService.synchronize).mockResolvedValue({
        status: 'skipped',
        reason: 'sync_in_progress',
      });

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(syncStatusStore.record).not.toHaveBeenCalled();
    });
  });
});
