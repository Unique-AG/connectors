import { SchedulerRegistry } from '@nestjs/schedule';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TenantAuth } from '../tenant/tenant-auth.interface';
import type { TenantContext } from '../tenant/tenant-context.interface';
import { getCurrentTenant } from '../tenant/tenant-context.storage';
import { TenantRegistry } from '../tenant/tenant-registry';
import { smear } from '../utils/logging.util';
import { TenantSyncScheduler } from './tenant-sync.scheduler';

function createMockTenant(name: string, overrides: Partial<TenantContext> = {}): TenantContext {
  return {
    name,
    config: {
      processing: { scanIntervalCron: '*/5 * * * *' },
    },
    logger: {
      log: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    },
    auth: {
      getAccessToken: vi.fn().mockResolvedValue('mock-token-12345678'),
    } satisfies TenantAuth,
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
    getAll: vi.fn().mockReturnValue(tenants),
    size: tenants.length,
  } as unknown as TenantRegistry;
}

describe('TenantSyncScheduler', () => {
  let scheduler: TenantSyncScheduler;
  let registry: TenantRegistry;
  let schedulerRegistry: SchedulerRegistry;
  let tenantA: TenantContext;
  let tenantB: TenantContext;

  beforeEach(() => {
    tenantA = createMockTenant('tenant-a');
    tenantB = createMockTenant('tenant-b');

    registry = createMockTenantRegistry([tenantA, tenantB]);
    schedulerRegistry = createMockSchedulerRegistry();
    scheduler = new TenantSyncScheduler(registry, schedulerRegistry);
  });

  describe('onModuleInit', () => {
    it('registers a cron job per tenant', () => {
      scheduler.onModuleInit();

      expect(schedulerRegistry.addCronJob).toHaveBeenCalledTimes(2);
      expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith('sync:tenant-a', expect.anything());
      expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith('sync:tenant-b', expect.anything());
    });

    it('triggers initial sync for each tenant', () => {
      scheduler.onModuleInit();

      expect(tenantA.auth.getAccessToken).toHaveBeenCalledOnce();
      expect(tenantB.auth.getAccessToken).toHaveBeenCalledOnce();
    });

    it('logs the scheduled cron expression per tenant', () => {
      scheduler.onModuleInit();

      expect(tenantA.logger.log).toHaveBeenCalledWith('Scheduled sync with cron: */5 * * * *');
      expect(tenantB.logger.log).toHaveBeenCalledWith('Scheduled sync with cron: */5 * * * *');
    });

    it('skips scheduling when no tenants are registered', () => {
      const emptyRegistry = createMockTenantRegistry([]);
      const emptyScheduler = new TenantSyncScheduler(emptyRegistry, schedulerRegistry);

      emptyScheduler.onModuleInit();

      expect(emptyRegistry.getAll).not.toHaveBeenCalled();
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
    it('acquires a token and logs smeared success', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(tenantA.auth.getAccessToken).toHaveBeenCalledOnce();
      expect(tenantA.logger.log).toHaveBeenCalledWith('Starting sync');
      expect(tenantA.logger.log).toHaveBeenCalledWith(
        `Token acquired successfully (${smear('mock-token-12345678')})`,
      );
    });

    it('sets AsyncLocalStorage context during sync', async () => {
      let capturedTenant: TenantContext | undefined;
      vi.mocked(tenantA.auth.getAccessToken).mockImplementation(async () => {
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

      expect(tenantA.auth.getAccessToken).not.toHaveBeenCalled();
      expect(tenantA.logger.log).toHaveBeenCalledWith('Sync already in progress, skipping');
    });

    it('resets isScanning after successful sync', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(tenantA.isScanning).toBe(false);
    });

    it('resets isScanning after failed sync', async () => {
      vi.mocked(tenantA.auth.getAccessToken).mockRejectedValue(new Error('auth failure'));

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(tenantA.isScanning).toBe(false);
      expect(tenantA.logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Sync failed' }),
      );
    });

    it('skips sync when shutting down', async () => {
      scheduler.onModuleInit();
      scheduler.onModuleDestroy();

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(tenantA.logger.log).toHaveBeenCalledWith('Skipping sync due to shutdown');
    });

    it('isolates errors between tenants', async () => {
      vi.mocked(tenantA.auth.getAccessToken).mockRejectedValue(new Error('tenant-a failed'));

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantB);

      expect(tenantA.logger.error).toHaveBeenCalled();
      expect(tenantB.auth.getAccessToken).toHaveBeenCalledOnce();
      expect(tenantB.logger.log).toHaveBeenCalledWith('Starting sync');
    });
  });
});
