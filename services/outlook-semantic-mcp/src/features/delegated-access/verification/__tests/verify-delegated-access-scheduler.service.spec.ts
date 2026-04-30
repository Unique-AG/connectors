/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { VerifyDelegatedAccessSchedulerService } from '../verify-delegated-access-scheduler.service';

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
  return { delegatedAccessVerificationCronSchedule: '0 */4 * * *' };
}

function createService({ amqp = createMockAmqp() } = {}) {
  const schedulerRegistry = createMockSchedulerRegistry();
  return new VerifyDelegatedAccessSchedulerService(
    schedulerRegistry as any,
    amqp as any,
    createMockConfig() as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('VerifyDelegatedAccessSchedulerService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('triggerVerificationForPipelineRows', () => {
    it('publishes a single sync event', async () => {
      const amqp = createMockAmqp();
      const service = createService({ amqp });

      await service.triggerVerificationForPipelineRows();

      expect(amqp.publish).toHaveBeenCalledOnce();
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        'unique.outlook-semantic-mcp.delegated-access.sync',
        expect.objectContaining({
          type: 'unique.outlook-semantic-mcp.delegated-access.sync',
          payload: {},
        }),
      );
    });

    it('skips when service is shutting down', async () => {
      const amqp = createMockAmqp();
      const service = createService({ amqp });

      service.onModuleDestroy();

      await service.triggerVerificationForPipelineRows();

      expect(amqp.publish).not.toHaveBeenCalled();
    });

    it('does throw on publish error', async () => {
      const amqp = createMockAmqp();
      amqp.publish.mockRejectedValue(new Error('AMQP error'));
      const service = createService({ amqp });

      await expect(service.triggerVerificationForPipelineRows()).rejects.toThrow();
    });
  });

  describe('lifecycle', () => {
    it('registers cron job on module init', () => {
      const schedulerRegistry = createMockSchedulerRegistry();
      const service = new VerifyDelegatedAccessSchedulerService(
        schedulerRegistry as any,
        createMockAmqp() as any,
        createMockConfig() as any,
      );

      service.onModuleInit();

      expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith(
        'delegated-access-sync',
        expect.anything(),
      );
    });

    it('stops cron job on module destroy', () => {
      const stopFn = vi.fn();
      const schedulerRegistry = createMockSchedulerRegistry();
      schedulerRegistry.getCronJob.mockReturnValue({ stop: stopFn });
      const service = new VerifyDelegatedAccessSchedulerService(
        schedulerRegistry as any,
        createMockAmqp() as any,
        createMockConfig() as any,
      );

      service.onModuleDestroy();

      expect(schedulerRegistry.getCronJob).toHaveBeenCalledWith('delegated-access-sync');
      expect(stopFn).toHaveBeenCalledOnce();
    });
  });
});
