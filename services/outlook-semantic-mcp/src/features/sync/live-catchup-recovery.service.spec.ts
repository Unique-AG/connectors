/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveCatchupRecoveryService } from './live-catchup-recovery.service';

vi.mock('~/features/tracing.utils', () => ({ traceEvent: vi.fn() }));

import { traceEvent } from '~/features/tracing.utils';

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

function createMockDb({ liveCatchUpRows = [] as Array<{ userProfileId: string }> } = {}) {
  const makeSelectChain = (rows: unknown[]) => ({
    from: vi.fn().mockReturnValue({
      where: vi.fn().mockResolvedValue(rows),
    }),
  });

  const select = vi.fn(() => makeSelectChain(liveCatchUpRows));

  return { select };
}

function createService({ amqp = createMockAmqp(), db = createMockDb() } = {}) {
  const schedulerRegistry = createMockSchedulerRegistry();
  return new LiveCatchupRecoveryService(schedulerRegistry as any, amqp as any, db as any);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LiveCatchupRecoveryService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('recoverStuckLiveCatchUps', () => {
    it('does nothing when no stuck live catch-up configs are found', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({ liveCatchUpRows: [] });
      const service = createService({ amqp, db });

      await service.runRecoveryScan();

      expect(amqp.publish).not.toHaveBeenCalled();
      expect(traceEvent).not.toHaveBeenCalled();
    });

    it('publishes a recovery event and emits trace event for a stuck live catch-up', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        liveCatchUpRows: [{ userProfileId: USER_PROFILE_ID_1 }],
      });
      const service = createService({ amqp, db });

      await service.runRecoveryScan();

      expect(amqp.publish).toHaveBeenCalledTimes(1);
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        'unique.outlook-semantic-mcp.live-catch-up.recovery',
        expect.objectContaining({
          type: 'unique.outlook-semantic-mcp.live-catch-up.recovery',
          payload: { userProfileId: USER_PROFILE_ID_1 },
        }),
      );
      expect(traceEvent).toHaveBeenCalledWith('live-catch-up stuck recovery triggered', {
        count: 1,
        userProfileIds: [USER_PROFILE_ID_1],
      });
    });

    it('publishes recovery events and traces for each stuck live catch-up config', async () => {
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
