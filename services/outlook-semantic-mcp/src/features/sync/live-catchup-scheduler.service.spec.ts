/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */

import { CronJob } from 'cron';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveCatchupSchedulerService } from './live-catchup-scheduler.service';

vi.mock('~/features/tracing.utils', () => ({
  traceEvent: vi.fn(),
  NewTrace: () => () => ({}),
}));

vi.mock('cron', () => ({
  CronJob: vi.fn(() => ({ start: vi.fn(), stop: vi.fn() })),
}));

// Avoid drizzle's union() being called on mock query builders
vi.mock('~/features/sync/sync-scheduler.utils', async () => {
  const { sql } = await import('drizzle-orm');
  return {
    selectUserProfileIdsWhichCanRunTheSyncProcess: vi.fn(() => sql`NULL`),
  };
});

import { traceEvent } from '~/features/tracing.utils';

// ---------------------------------------------------------------------------
// Constants
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

function makeSelectChain(rows: unknown[]) {
  const chain: any = {
    from: vi.fn(() => ({
      where: vi.fn().mockResolvedValue(rows),
      innerJoin: vi.fn(() => ({
        where: vi.fn().mockResolvedValue(rows),
        innerJoin: vi.fn(() => ({
          where: vi.fn().mockResolvedValue(rows),
        })),
      })),
    })),
  };
  return chain;
}

function createMockDb({ liveCatchUpRows = [] as Array<{ userProfileId: string }> } = {}) {
  return { select: vi.fn(() => makeSelectChain(liveCatchUpRows)) };
}

function createService({ amqp = createMockAmqp(), db = createMockDb() } = {}) {
  return new LiveCatchupSchedulerService(
    createMockSchedulerRegistry() as any,
    amqp as any,
    {} as any,
    db as any,
  );
}

function createServiceWithIngestionConfig({ amqp = createMockAmqp(), db = createMockDb() } = {}) {
  return new LiveCatchupSchedulerService(
    createMockSchedulerRegistry() as any,
    amqp as any,
    {
      mcpBackend: 'MicrosoftGraphAndUniqueApi',
      liveCatchupRecoveryCron: '*/5 * * * *',
      liveCatchupRecheckCron: '*/10 * * * *',
      liveCatchupSharedMailboxRecheckCron: '*/2 * * * *',
    } as any,
    db as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LiveCatchupSchedulerService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(CronJob).mockImplementation(() => ({ start: vi.fn(), stop: vi.fn() }) as any);
  });

  describe('cron job wiring', () => {
    it('recovery cron fires runRecoveryScan', async () => {
      const service = createServiceWithIngestionConfig();
      vi.spyOn(service, 'runRecoveryScan').mockResolvedValue(undefined);
      vi.spyOn(service, 'runStuckLiveCatchups').mockResolvedValue(undefined);
      vi.spyOn(service, 'runLiveCatchupsWhichDidNotRunRecently').mockResolvedValue(undefined);

      service.onModuleInit();

      const recoveryCallback = vi.mocked(CronJob).mock.calls[0]![1] as () => void;
      await recoveryCallback();

      expect(service.runRecoveryScan).toHaveBeenCalledOnce();
      expect(service.runStuckLiveCatchups).not.toHaveBeenCalled();
      expect(service.runLiveCatchupsWhichDidNotRunRecently).not.toHaveBeenCalled();
    });

    it('recheck cron fires runStuckLiveCatchups', async () => {
      const service = createServiceWithIngestionConfig();
      vi.spyOn(service, 'runRecoveryScan').mockResolvedValue(undefined);
      vi.spyOn(service, 'runStuckLiveCatchups').mockResolvedValue(undefined);
      vi.spyOn(service, 'runLiveCatchupsWhichDidNotRunRecently').mockResolvedValue(undefined);

      service.onModuleInit();

      const recheckCallback = vi.mocked(CronJob).mock.calls[1]![1] as () => void;
      await recheckCallback();

      expect(service.runStuckLiveCatchups).toHaveBeenCalledOnce();
      expect(service.runRecoveryScan).not.toHaveBeenCalled();
      expect(service.runLiveCatchupsWhichDidNotRunRecently).not.toHaveBeenCalled();
    });

    it('shared-mailbox recheck cron fires runLiveCatchupsWhichDidNotRunRecently', async () => {
      const service = createServiceWithIngestionConfig();
      vi.spyOn(service, 'runRecoveryScan').mockResolvedValue(undefined);
      vi.spyOn(service, 'runStuckLiveCatchups').mockResolvedValue(undefined);
      vi.spyOn(service, 'runLiveCatchupsWhichDidNotRunRecently').mockResolvedValue(undefined);

      service.onModuleInit();

      const sharedMailboxCallback = vi.mocked(CronJob).mock.calls[2]![1] as () => void;
      await sharedMailboxCallback();

      expect(service.runLiveCatchupsWhichDidNotRunRecently).toHaveBeenCalledOnce();
      expect(service.runRecoveryScan).not.toHaveBeenCalled();
      expect(service.runStuckLiveCatchups).not.toHaveBeenCalled();
    });
  });

  describe('runRecoveryScan', () => {
    it('does nothing when no stuck live catch-up configs are found', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({ liveCatchUpRows: [] });
      const service = createService({ amqp, db });

      await service.runRecoveryScan();

      expect(amqp.publish).not.toHaveBeenCalled();
      expect(traceEvent).not.toHaveBeenCalled();
    });

    it('publishes an execute event for a stuck live catch-up', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        liveCatchUpRows: [{ userProfileId: USER_PROFILE_ID_1 }],
      });
      const service = createService({ amqp, db });

      await service.runRecoveryScan();

      expect(amqp.publish).toHaveBeenCalledTimes(1);
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        'unique.outlook-semantic-mcp.live-catch-up.execute',
        expect.objectContaining({
          type: 'unique.outlook-semantic-mcp.live-catch-up.execute',
          payload: { userProfileId: USER_PROFILE_ID_1 },
        }),
      );
      expect(traceEvent).toHaveBeenCalledWith('live-catch-up stuck recovery triggered', {
        count: 1,
        userProfileIds: [USER_PROFILE_ID_1],
      });
    });

    it('publishes execute events for each stuck live catch-up config', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        liveCatchUpRows: [
          { userProfileId: USER_PROFILE_ID_1 },
          { userProfileId: USER_PROFILE_ID_2 },
        ],
      });
      const service = createService({ amqp, db });

      await service.runRecoveryScan();

      expect(amqp.publish).toHaveBeenCalledTimes(2);
      expect(traceEvent).toHaveBeenCalledWith('live-catch-up stuck recovery triggered', {
        count: 2,
        userProfileIds: [USER_PROFILE_ID_1, USER_PROFILE_ID_2],
      });
    });
  });
});
