/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveCatchupSchedulerService } from './live-catchup-scheduler.service';

vi.mock('~/features/tracing.utils', () => ({ traceEvent: vi.fn() }));

import { traceEvent } from '~/features/tracing.utils';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SUBSCRIPTION_ID_1 = 'sub_01jxk5r1s2fq9att23mp4z5ef2';
const SUBSCRIPTION_ID_2 = 'sub_01jxk5r1s2fq9att23mp4z5ef3';

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

function createMockDb({ liveCatchUpRows = [] as Array<string> } = {}) {
  const makeSelectChain = (rows: unknown[]) => ({
    from: vi.fn().mockReturnValue({
      innerJoin: vi.fn().mockReturnValue({
        where: vi.fn().mockResolvedValue(rows),
      }),
    }),
  });

  const select = vi.fn(() => makeSelectChain(liveCatchUpRows));

  return { select };
}

function createService({ amqp = createMockAmqp(), db = createMockDb() } = {}) {
  const schedulerRegistry = createMockSchedulerRegistry();
  return new LiveCatchupSchedulerService(schedulerRegistry as any, amqp as any, db as any);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LiveCatchupSchedulerService', () => {
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

    it('publishes an execute event and emits trace event for a stuck live catch-up', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        liveCatchUpRows: [SUBSCRIPTION_ID_1],
      });
      const service = createService({ amqp, db });

      await service.runRecoveryScan();

      expect(amqp.publish).toHaveBeenCalledTimes(1);
      expect(amqp.publish).toHaveBeenCalledWith(
        expect.any(String),
        'unique.outlook-semantic-mcp.live-catch-up.execute',
        expect.objectContaining({
          type: 'unique.outlook-semantic-mcp.live-catch-up.execute',
          payload: { subscriptionId: SUBSCRIPTION_ID_1 },
        }),
      );
      expect(traceEvent).toHaveBeenCalledWith('live-catch-up stuck recovery triggered', {
        count: 1,
        subscriptionIds: [SUBSCRIPTION_ID_1],
      });
    });

    it('publishes execute events and traces for each stuck live catch-up config', async () => {
      const amqp = createMockAmqp();
      const db = createMockDb({
        liveCatchUpRows: [SUBSCRIPTION_ID_1, SUBSCRIPTION_ID_2],
      });
      const service = createService({ amqp, db });

      await service.runRecoveryScan();

      expect(amqp.publish).toHaveBeenCalledTimes(2);
      expect(traceEvent).toHaveBeenCalledWith('live-catch-up stuck recovery triggered', {
        count: 2,
        subscriptionIds: [SUBSCRIPTION_ID_1, SUBSCRIPTION_ID_2],
      });
    });
  });
});
