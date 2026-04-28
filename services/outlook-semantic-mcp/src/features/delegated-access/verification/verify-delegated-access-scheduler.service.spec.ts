/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { VerifyDelegatedAccessSchedulerService } from './verify-delegated-access-scheduler.service';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const PIPELINE_ID_1 = 'dap_01jxk5r1s2fq9att23mp4z5ef2';
const PIPELINE_ID_2 = 'dap_01jxk5r1s2fq9att23mp4z5ef3';

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

function createMockDb({ rows = [] as Array<{ id: string }> } = {}) {
  const makeSelectChain = (data: unknown[]) => ({
    from: vi.fn().mockResolvedValue(data),
  });

  const select = vi.fn(() => makeSelectChain(rows));

  return { select };
}

function createMockConfig() {
  return { delegatedAccessVerificationCronSchedule: '0 */4 * * *' };
}

function createService({ amqp = createMockAmqp(), db = createMockDb() } = {}) {
  const schedulerRegistry = createMockSchedulerRegistry();
  return new VerifyDelegatedAccessSchedulerService(
    schedulerRegistry as any,
    amqp as any,
    db as any,
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
    it('does nothing when no pipeline rows are found', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({ rows: [] });
      const service = createService({ amqp, db });

      await service.triggerVerificationForPipelineRows();

      expect(amqp.publish).not.toHaveBeenCalled();
    });

    it('publishes one verify event per pipeline row', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({ rows: [{ id: PIPELINE_ID_1 }] });
      const service = createService({ amqp, db });

      await service.triggerVerificationForPipelineRows();

      expect(amqp.publish).toHaveBeenCalledTimes(1);
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        `unique.outlook-semantic-mcp.delegated-access.verify.${PIPELINE_ID_1}`,
        expect.objectContaining({
          type: 'unique.outlook-semantic-mcp.delegated-access.verify',
          payload: { pipelineId: PIPELINE_ID_1 },
        }),
      );
    });

    it('publishes verify events for multiple pipeline rows', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({ rows: [{ id: PIPELINE_ID_1 }, { id: PIPELINE_ID_2 }] });
      const service = createService({ amqp, db });

      await service.triggerVerificationForPipelineRows();

      expect(amqp.publish).toHaveBeenCalledTimes(2);
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        `unique.outlook-semantic-mcp.delegated-access.verify.${PIPELINE_ID_1}`,
        expect.objectContaining({ payload: { pipelineId: PIPELINE_ID_1 } }),
      );
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        `unique.outlook-semantic-mcp.delegated-access.verify.${PIPELINE_ID_2}`,
        expect.objectContaining({ payload: { pipelineId: PIPELINE_ID_2 } }),
      );
    });

    it('skips when service is shutting down', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({ rows: [{ id: PIPELINE_ID_1 }] });
      const service = createService({ amqp, db });

      service.onModuleDestroy();

      await service.triggerVerificationForPipelineRows();

      expect(amqp.publish).not.toHaveBeenCalled();
      expect(db.select).not.toHaveBeenCalled();
    });

    it('does throw on publish error', async () => {
      const amqp = createMockAmqp();
      amqp.publish.mockRejectedValue(new Error('AMQP error'));
      const db = createMockDb({ rows: [{ id: PIPELINE_ID_1 }] });
      const service = createService({ amqp, db });

      await expect(service.triggerVerificationForPipelineRows()).rejects.toThrow();
    });

    it('does throw on db query error', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb();
      db.select.mockImplementation(() => {
        throw new Error('DB error');
      });
      const service = createService({ amqp, db });

      await expect(service.triggerVerificationForPipelineRows()).rejects.toThrow();
      expect(amqp.publish).not.toHaveBeenCalled();
    });
  });

  describe('lifecycle', () => {
    it('registers cron job on module init', () => {
      const schedulerRegistry = createMockSchedulerRegistry();
      const service = new VerifyDelegatedAccessSchedulerService(
        schedulerRegistry as any,
        createMockAmqp() as any,
        createMockDb() as any,
        createMockConfig() as any,
      );

      service.onModuleInit();

      expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith(
        'delegated-access-verification',
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
        createMockDb() as any,
        createMockConfig() as any,
      );

      service.onModuleDestroy();

      expect(schedulerRegistry.getCronJob).toHaveBeenCalledWith('delegated-access-verification');
      expect(stopFn).toHaveBeenCalledOnce();
    });
  });
});
