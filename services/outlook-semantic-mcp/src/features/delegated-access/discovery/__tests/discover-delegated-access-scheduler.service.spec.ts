/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DiscoverDelegatedAccessSchedulerService } from '../discover-delegated-access-scheduler.service';

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function createMockSchedulerRegistry() {
  return {
    addCronJob: vi.fn(),
    getCronJob: vi.fn().mockReturnValue({ stop: vi.fn() }),
  };
}

function createMockAmqp() {
  return { publish: vi.fn().mockResolvedValue(undefined) };
}

function createMockConfig() {
  return { delegatedAccessDiscoveryCronSchedule: '0 */6 * * *' };
}

function createService({ amqp = createMockAmqp() } = {}) {
  const schedulerRegistry = createMockSchedulerRegistry();
  return new DiscoverDelegatedAccessSchedulerService(
    schedulerRegistry as any,
    amqp as any,
    createMockConfig() as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DiscoverDelegatedAccessSchedulerService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('triggerDiscovery', () => {
    it('publishes a single discovery event', async () => {
      const amqp = createMockAmqp();
      const service = createService({ amqp });

      await service.triggerDiscovery();

      expect(amqp.publish).toHaveBeenCalledOnce();
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        'unique.outlook-semantic-mcp.delegated-access.discover',
        expect.objectContaining({
          type: 'unique.outlook-semantic-mcp.delegated-access.discover',
          payload: {},
        }),
      );
    });

    it('skips when service is shutting down', async () => {
      const amqp = createMockAmqp();
      const service = createService({ amqp });

      service.onModuleDestroy();

      await service.triggerDiscovery();

      expect(amqp.publish).not.toHaveBeenCalled();
    });

    it('throws on publish error', async () => {
      const amqp = createMockAmqp();
      amqp.publish.mockRejectedValue(new Error('AMQP error'));
      const service = createService({ amqp });

      await expect(service.triggerDiscovery()).rejects.toThrow();
    });
  });

  describe('lifecycle', () => {
    it('registers cron job on module init', () => {
      const schedulerRegistry = createMockSchedulerRegistry();
      const service = new DiscoverDelegatedAccessSchedulerService(
        schedulerRegistry as any,
        createMockAmqp() as any,
        createMockConfig() as any,
      );

      service.onModuleInit();

      expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith(
        'delegated-access-discovery',
        expect.anything(),
      );
    });

    it('stops cron job on module destroy', () => {
      const stopFn = vi.fn();
      const schedulerRegistry = createMockSchedulerRegistry();
      schedulerRegistry.getCronJob.mockReturnValue({ stop: stopFn });
      const service = new DiscoverDelegatedAccessSchedulerService(
        schedulerRegistry as any,
        createMockAmqp() as any,
        createMockConfig() as any,
      );

      service.onModuleDestroy();

      expect(schedulerRegistry.getCronJob).toHaveBeenCalledWith('delegated-access-discovery');
      expect(stopFn).toHaveBeenCalledOnce();
    });
  });
});
