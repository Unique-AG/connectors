/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FullSyncSchedulerService } from './full-sync-scheduler.service';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const USER_PROFILE_ID_1 = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const USER_PROFILE_ID_2 = 'user_profile_01jxk5r1s2fq9att23mp4z5ef3';

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

function createMockDb({ rows = [] as Array<{ userProfileId: string }> } = {}) {
  const makeSelectChain = (data: unknown[]) => ({
    from: vi.fn().mockReturnValue({
      innerJoin: vi.fn().mockReturnValue({
        where: vi.fn().mockResolvedValue(data),
      }),
    }),
  });

  const select = vi.fn(() => makeSelectChain(rows));

  return { select };
}

function createService({ amqp = createMockAmqp(), db = createMockDb() } = {}) {
  const schedulerRegistry = createMockSchedulerRegistry();
  return new FullSyncSchedulerService(schedulerRegistry as any, amqp as any, db as any);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FullSyncRecoveryService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('publishRetriggerEvents', () => {
    it('does nothing when no retriggerable configs are found', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({ rows: [] });
      const service = createService({ amqp, db });

      await service.checkAndRetriggerStuckFullSyncs();

      expect(amqp.publish).not.toHaveBeenCalled();
    });

    it('publishes retrigger event for a single config', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        rows: [{ userProfileId: USER_PROFILE_ID_1 }],
      });
      const service = createService({ amqp, db });

      await service.checkAndRetriggerStuckFullSyncs();

      expect(amqp.publish).toHaveBeenCalledTimes(1);
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        'unique.outlook-semantic-mcp.full-sync.retrigger',
        expect.objectContaining({
          type: 'unique.outlook-semantic-mcp.full-sync.retrigger',
          payload: { userProfileId: USER_PROFILE_ID_1 },
        }),
      );
    });

    it('publishes retrigger events for multiple configs', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        rows: [{ userProfileId: USER_PROFILE_ID_1 }, { userProfileId: USER_PROFILE_ID_2 }],
      });
      const service = createService({ amqp, db });

      await service.checkAndRetriggerStuckFullSyncs();

      expect(amqp.publish).toHaveBeenCalledTimes(2);
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        'unique.outlook-semantic-mcp.full-sync.retrigger',
        expect.objectContaining({
          payload: { userProfileId: USER_PROFILE_ID_1 },
        }),
      );
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        'unique.outlook-semantic-mcp.full-sync.retrigger',
        expect.objectContaining({
          payload: { userProfileId: USER_PROFILE_ID_2 },
        }),
      );
    });

    it('skips when service is shutting down', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        rows: [{ userProfileId: USER_PROFILE_ID_1 }],
      });
      const service = createService({ amqp, db });

      // Trigger shutdown
      service.onModuleDestroy();

      await service.checkAndRetriggerStuckFullSyncs();

      expect(amqp.publish).not.toHaveBeenCalled();
      expect(db.select).not.toHaveBeenCalled();
    });

    it('does throw on publish error', async () => {
      const amqp = createMockAmqp();
      amqp.publish.mockRejectedValue(new Error('AMQP error'));
      const db = createMockDb({
        rows: [{ userProfileId: USER_PROFILE_ID_1 }],
      });
      const service = createService({ amqp, db });

      await expect(service.checkAndRetriggerStuckFullSyncs()).rejects.toThrow();
    });

    it('does throw on db query error', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb();
      // Override select to throw
      db.select.mockImplementation(() => {
        throw new Error('DB error');
      });
      const service = createService({ amqp, db });

      await expect(service.checkAndRetriggerStuckFullSyncs()).rejects.toThrow();
      expect(amqp.publish).not.toHaveBeenCalled();
    });
  });

  describe('DB query filter verification', () => {
    it('queries the database with the correct where clause shape', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({ rows: [] });
      const service = createService({ amqp, db });

      await service.checkAndRetriggerStuckFullSyncs();

      // Verify select was called (the query was made)
      expect(db.select).toHaveBeenCalledOnce();

      // The chain: select({...}).from(...).innerJoin(...).where(...)
      const selectResult = db.select.mock.results?.[0]?.value;
      expect(selectResult?.from).toHaveBeenCalledOnce();

      const fromResult = selectResult.from.mock.results[0]?.value;
      expect(fromResult?.innerJoin).toHaveBeenCalledOnce();

      const innerJoinResult = fromResult.innerJoin.mock.results[0]?.value;
      expect(innerJoinResult?.where).toHaveBeenCalledOnce();
    });
  });

  describe('lifecycle', () => {
    it('registers cron job on module init', () => {
      const schedulerRegistry = createMockSchedulerRegistry();
      const service = new FullSyncSchedulerService(
        schedulerRegistry as any,
        createMockAmqp() as any,
        createMockDb() as any,
      );

      service.onModuleInit();

      expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith(
        'full-sync-recovery',
        expect.anything(),
      );
    });

    it('stops cron job on module destroy', () => {
      const stopFn = vi.fn();
      const schedulerRegistry = createMockSchedulerRegistry();
      schedulerRegistry.getCronJob.mockReturnValue({ stop: stopFn });
      const service = new FullSyncSchedulerService(
        schedulerRegistry as any,
        createMockAmqp() as any,
        createMockDb() as any,
      );

      service.onModuleDestroy();

      expect(schedulerRegistry.getCronJob).toHaveBeenCalledWith('full-sync-recovery');
      expect(stopFn).toHaveBeenCalledOnce();
    });
  });
});
