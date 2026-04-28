/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DiscoverDelegatedAccessSchedulerService } from './discover-delegated-access-scheduler.service';

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
      where: vi.fn().mockResolvedValue(data),
    }),
  });

  const select = vi.fn(() => makeSelectChain(rows));

  return { select };
}

function createService({ amqp = createMockAmqp(), db = createMockDb() } = {}) {
  const schedulerRegistry = createMockSchedulerRegistry();
  return new DiscoverDelegatedAccessSchedulerService(
    schedulerRegistry as any,
    amqp as any,
    db as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DiscoverDelegatedAccessSchedulerService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('triggerDiscoveryForConnectedUsers', () => {
    it('does nothing when no connected users are found', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({ rows: [] });
      const service = createService({ amqp, db });

      await service.triggerDiscoveryForConnectedUsers();

      expect(amqp.publish).not.toHaveBeenCalled();
    });

    it('publishes one discovery event per connected user', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        rows: [{ userProfileId: USER_PROFILE_ID_1 }],
      });
      const service = createService({ amqp, db });

      await service.triggerDiscoveryForConnectedUsers();

      expect(amqp.publish).toHaveBeenCalledTimes(1);
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        `unique.outlook-semantic-mcp.delegated-access.discover.${USER_PROFILE_ID_1}`,
        expect.objectContaining({
          type: 'unique.outlook-semantic-mcp.delegated-access.discover',
          payload: { delegateUserId: USER_PROFILE_ID_1 },
        }),
      );
    });

    it('publishes discovery events for multiple connected users', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        rows: [{ userProfileId: USER_PROFILE_ID_1 }, { userProfileId: USER_PROFILE_ID_2 }],
      });
      const service = createService({ amqp, db });

      await service.triggerDiscoveryForConnectedUsers();

      expect(amqp.publish).toHaveBeenCalledTimes(2);
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        `unique.outlook-semantic-mcp.delegated-access.discover.${USER_PROFILE_ID_1}`,
        expect.objectContaining({
          payload: { delegateUserId: USER_PROFILE_ID_1 },
        }),
      );
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        `unique.outlook-semantic-mcp.delegated-access.discover.${USER_PROFILE_ID_2}`,
        expect.objectContaining({
          payload: { delegateUserId: USER_PROFILE_ID_2 },
        }),
      );
    });

    it('skips when service is shutting down', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        rows: [{ userProfileId: USER_PROFILE_ID_1 }],
      });
      const service = createService({ amqp, db });

      service.onModuleDestroy();

      await service.triggerDiscoveryForConnectedUsers();

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

      await expect(service.triggerDiscoveryForConnectedUsers()).rejects.toThrow();
    });

    it('does throw on db query error', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb();
      db.select.mockImplementation(() => {
        throw new Error('DB error');
      });
      const service = createService({ amqp, db });

      await expect(service.triggerDiscoveryForConnectedUsers()).rejects.toThrow();
      expect(amqp.publish).not.toHaveBeenCalled();
    });
  });

  describe('DB query filter verification', () => {
    it('queries the database for users with active subscriptions', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({ rows: [] });
      const service = createService({ amqp, db });

      await service.triggerDiscoveryForConnectedUsers();

      expect(db.select).toHaveBeenCalledOnce();

      // The chain: select({...}).from(...).where(...)
      const selectResult = db.select.mock.results?.[0]?.value;
      expect(selectResult?.from).toHaveBeenCalledOnce();

      const fromResult = selectResult.from.mock.results[0]?.value;
      expect(fromResult?.where).toHaveBeenCalledOnce();
    });
  });

  describe('lifecycle', () => {
    it('registers cron job on module init', () => {
      const schedulerRegistry = createMockSchedulerRegistry();
      const service = new DiscoverDelegatedAccessSchedulerService(
        schedulerRegistry as any,
        createMockAmqp() as any,
        createMockDb() as any,
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
        createMockDb() as any,
      );

      service.onModuleDestroy();

      expect(schedulerRegistry.getCronJob).toHaveBeenCalledWith('delegated-access-discovery');
      expect(stopFn).toHaveBeenCalledOnce();
    });
  });
});
