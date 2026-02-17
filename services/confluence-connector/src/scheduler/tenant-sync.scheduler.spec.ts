import { SchedulerRegistry } from '@nestjs/schedule';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfluenceAuth } from '../auth/confluence-auth';
import { ServiceRegistry } from '../tenant/service-registry';
import type { TenantContext } from '../tenant/tenant-context.interface';
import { getCurrentTenant, tenantStorage } from '../tenant/tenant-context.storage';
import { TenantRegistry } from '../tenant/tenant-registry';
import { smear } from '../utils/logging.util';
import { TenantSyncScheduler } from './tenant-sync.scheduler';

const mockTenantLogger = vi.hoisted(() => ({
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
}));

function createMockAuth(): ConfluenceAuth {
  return {
    acquireToken: vi.fn().mockResolvedValue('mock-token-12345678'),
  } as ConfluenceAuth;
}

function createMockTenant(name: string, overrides: Partial<TenantContext> = {}): TenantContext {
  return {
    name,
    config: {
      processing: { scanIntervalCron: '*/5 * * * *' },
    },
    isScanning: false,
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
  const mockBaseLogger = {
    child: () => mockTenantLogger,
  };
  for (const tenant of tenants) {
    serviceRegistry.registerTenantLogger(tenant.name, mockBaseLogger as never);
    serviceRegistry.register(tenant.name, ConfluenceAuth, createMockAuth());
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
        const authA = tenantStorage.run(tenantA, () => serviceRegistry.getService(ConfluenceAuth));
        expect(authA.acquireToken).toHaveBeenCalledOnce();
        const authB = tenantStorage.run(tenantB, () => serviceRegistry.getService(ConfluenceAuth));
        expect(authB.acquireToken).toHaveBeenCalledOnce();
      });
    });

    it('logs the scheduled cron expression via ServiceRegistry.getServiceLogger', () => {
      scheduler.onModuleInit();

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Scheduled sync with cron: */5 * * * *');
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
    it('creates a structured logger via ServiceRegistry.getServiceLogger', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Starting sync');
    });

    it('acquires a token and logs via ServiceRegistry.getServiceLogger', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      const auth = tenantStorage.run(tenantA, () => serviceRegistry.getService(ConfluenceAuth));
      expect(auth.acquireToken).toHaveBeenCalledOnce();
      expect(mockTenantLogger.info).toHaveBeenCalledWith('Starting sync');
      expect(mockTenantLogger.info).toHaveBeenCalledWith(
        { token: smear('mock-token-12345678') },
        'Token acquired',
      );
    });

    it('sets AsyncLocalStorage context during sync', async () => {
      let capturedTenant: TenantContext | undefined;
      const auth = tenantStorage.run(tenantA, () => serviceRegistry.getService(ConfluenceAuth));
      vi.mocked(auth.acquireToken).mockImplementation(async () => {
        capturedTenant = getCurrentTenant();
        return 'mock-token-12345678';
      });

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(capturedTenant).toBe(tenantA);
    });

    it('skips when tenant is already scanning', async () => {
      tenantA.isScanning = true;

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      const auth = tenantStorage.run(tenantA, () => serviceRegistry.getService(ConfluenceAuth));
      expect(auth.acquireToken).not.toHaveBeenCalled();
      expect(mockTenantLogger.info).toHaveBeenCalledWith('Sync already in progress, skipping');
    });

    it('resets isScanning after successful sync', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(tenantA.isScanning).toBe(false);
    });

    it('resets isScanning after failed sync', async () => {
      const auth = tenantStorage.run(tenantA, () => serviceRegistry.getService(ConfluenceAuth));
      vi.mocked(auth.acquireToken).mockRejectedValue(new Error('auth failure'));

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(tenantA.isScanning).toBe(false);
      expect(mockTenantLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Sync failed' }),
      );
    });

    it('skips sync when shutting down', async () => {
      scheduler.onModuleInit();
      scheduler.onModuleDestroy();
      vi.clearAllMocks();

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Skipping sync due to shutdown');
    });

    it('isolates errors between tenants', async () => {
      const authA = tenantStorage.run(tenantA, () => serviceRegistry.getService(ConfluenceAuth));
      vi.mocked(authA.acquireToken).mockRejectedValue(new Error('tenant-a failed'));

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantB);

      expect(mockTenantLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Sync failed' }),
      );
      const authB = tenantStorage.run(tenantB, () => serviceRegistry.getService(ConfluenceAuth));
      expect(authB.acquireToken).toHaveBeenCalledOnce();
      expect(mockTenantLogger.info).toHaveBeenCalledWith('Starting sync');
    });
  });
});
