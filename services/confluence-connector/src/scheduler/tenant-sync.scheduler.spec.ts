import { SchedulerRegistry } from '@nestjs/schedule';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TenantAuth } from '../tenant/tenant-auth';
import type { TenantContext } from '../tenant/tenant-context.interface';
import { getCurrentTenant } from '../tenant/tenant-context.storage';
import { TenantRegistry } from '../tenant/tenant-registry';
import { TenantServiceRegistry } from '../tenant/tenant-service-registry';
import { smear } from '../utils/logging.util';
import { TenantSyncScheduler } from './tenant-sync.scheduler';

const mockTenantLogger = vi.hoisted(() => ({
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
}));

vi.mock('../tenant/tenant-logger', () => ({
  getTenantLogger: vi.fn().mockReturnValue(mockTenantLogger),
}));

import { getTenantLogger } from '../tenant/tenant-logger';

function createMockAuth(): TenantAuth {
  return { getAccessToken: vi.fn().mockResolvedValue('mock-token-12345678') } as TenantAuth;
}

function createMockTenant(name: string, overrides: Partial<TenantContext> = {}): TenantContext {
  const services = new TenantServiceRegistry().set(TenantAuth, createMockAuth());
  return {
    name,
    config: {
      processing: { scanIntervalCron: '*/5 * * * *' },
    },
    logger: {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    },
    services,
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
    vi.clearAllMocks();
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

      expect(tenantA.services.get(TenantAuth).getAccessToken).toHaveBeenCalledOnce();
      expect(tenantB.services.get(TenantAuth).getAccessToken).toHaveBeenCalledOnce();
    });

    it('logs the scheduled cron expression via getTenantLogger', () => {
      scheduler.onModuleInit();

      expect(getTenantLogger).toHaveBeenCalledWith(TenantSyncScheduler);
      expect(mockTenantLogger.info).toHaveBeenCalledWith('Scheduled sync with cron: */5 * * * *');
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
    it('creates a structured logger via getTenantLogger', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(getTenantLogger).toHaveBeenCalledWith(TenantSyncScheduler);
    });

    it('acquires a token and logs via getTenantLogger', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(tenantA.services.get(TenantAuth).getAccessToken).toHaveBeenCalledOnce();
      expect(mockTenantLogger.info).toHaveBeenCalledWith('Starting sync');
      expect(mockTenantLogger.info).toHaveBeenCalledWith(
        { token: smear('mock-token-12345678') },
        'Token acquired',
      );
    });

    it('sets AsyncLocalStorage context during sync', async () => {
      let capturedTenant: TenantContext | undefined;
      vi.mocked(tenantA.services.get(TenantAuth).getAccessToken).mockImplementation(async () => {
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

      expect(tenantA.services.get(TenantAuth).getAccessToken).not.toHaveBeenCalled();
      expect(mockTenantLogger.info).toHaveBeenCalledWith('Sync already in progress, skipping');
    });

    it('resets isScanning after successful sync', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);

      expect(tenantA.isScanning).toBe(false);
    });

    it('resets isScanning after failed sync', async () => {
      vi.mocked(tenantA.services.get(TenantAuth).getAccessToken).mockRejectedValue(
        new Error('auth failure'),
      );

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
      vi.mocked(tenantA.services.get(TenantAuth).getAccessToken).mockRejectedValue(
        new Error('tenant-a failed'),
      );

      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantA);
      // biome-ignore lint/suspicious/noExplicitAny: Access private method for testing
      await (scheduler as any).syncTenant(tenantB);

      expect(mockTenantLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Sync failed' }),
      );
      expect(tenantB.services.get(TenantAuth).getAccessToken).toHaveBeenCalledOnce();
      expect(mockTenantLogger.info).toHaveBeenCalledWith('Starting sync');
    });
  });
});
