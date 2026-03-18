/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FullSyncCommand, START_FULL_SYNC_LINK } from './full-sync.command';

vi.mock('~/features/tracing.utils', () => ({
  traceAttrs: vi.fn(),
  traceEvent: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';

function minutesAgo(minutes: number): Date {
  const d = new Date();
  d.setMinutes(d.getMinutes() - minutes);
  return d;
}

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function createMockGraphApi() {
  const api: Record<string, any> = {
    header: vi.fn().mockReturnThis(),
    get: vi.fn().mockResolvedValue(42),
  };
  return api;
}

function createMockGraphClientFactory(graphApi: ReturnType<typeof createMockGraphApi>) {
  return {
    createClientForUser: vi.fn().mockReturnValue({
      api: vi.fn().mockReturnValue(graphApi),
    }),
  };
}

function createMockProcessFullSyncBatchCommand(
  outcome: 'batch-uploaded' | 'completed' | 'version-mismatch' = 'completed',
) {
  return { run: vi.fn().mockResolvedValue({ outcome }) };
}

function createMockGetScopeIngestionStatsQuery(stats?: { ok: boolean; inProgress: number }) {
  return {
    run: vi.fn().mockResolvedValue(stats ?? { ok: true, inProgress: 5 }),
  };
}

function createMockUpdateByVersionCommand(success = true) {
  return { run: vi.fn().mockResolvedValue(success) };
}

function createMockDb({
  row,
}: {
  row?: {
    fullSyncState: string;
    fullSyncVersion: string | null;
    fullSyncNextLink: string | null;
    fullSyncHeartbeatAt: Date | null;
    fullSyncLastRunAt: Date | null;
    fullSyncExpectedTotal: number | null;
    newestLastModifiedDateTime: Date | null;
  };
}) {
  const txExecuteFn = vi.fn().mockResolvedValue(undefined);
  const txSelect = {
    from: vi.fn().mockReturnValue({
      where: vi.fn().mockReturnValue({
        for: vi.fn().mockResolvedValue(row ? [row] : []),
      }),
    }),
  };
  const txUpdate = {
    set: vi.fn().mockReturnValue({
      where: vi.fn().mockReturnValue({
        execute: txExecuteFn,
      }),
    }),
  };
  const tx = {
    select: vi.fn().mockReturnValue(txSelect),
    update: vi.fn().mockReturnValue(txUpdate),
  };

  return {
    transaction: vi.fn(async (cb: (tx: any) => Promise<any>) => cb(tx)),
    __tx: tx,
  };
}

function createCommand({
  graphApi = createMockGraphApi(),
  batchCommand = createMockProcessFullSyncBatchCommand(),
  statsQuery = createMockGetScopeIngestionStatsQuery(),
  updateByVersionCommand = createMockUpdateByVersionCommand(),
  db = createMockDb({ row: undefined }),
}: {
  graphApi?: ReturnType<typeof createMockGraphApi>;
  batchCommand?: ReturnType<typeof createMockProcessFullSyncBatchCommand>;
  statsQuery?: ReturnType<typeof createMockGetScopeIngestionStatsQuery>;
  updateByVersionCommand?: ReturnType<typeof createMockUpdateByVersionCommand>;
  db?: ReturnType<typeof createMockDb>;
} = {}): FullSyncCommand {
  return new FullSyncCommand(
    createMockGraphClientFactory(graphApi) as any,
    batchCommand as any,
    statsQuery as any,
    updateByVersionCommand as any,
    db as any,
  );
}

function makeRow(overrides: Partial<{
  fullSyncState: string;
  fullSyncVersion: string | null;
  fullSyncNextLink: string | null;
  fullSyncHeartbeatAt: Date | null;
  fullSyncLastRunAt: Date | null;
  fullSyncExpectedTotal: number | null;
  newestLastModifiedDateTime: Date | null;
}> = {}) {
  return {
    fullSyncState: 'ready' as string,
    fullSyncVersion: 'v1',
    fullSyncNextLink: null as string | null,
    fullSyncHeartbeatAt: null as Date | null,
    fullSyncLastRunAt: null as Date | null,
    fullSyncExpectedTotal: null as number | null,
    newestLastModifiedDateTime: null as Date | null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FullSyncCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -------------------------------------------------------------------------
  // State-machine decision logic
  // -------------------------------------------------------------------------

  describe('state machine decisions', () => {
    it('proceeds from ready state with no cooldown', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({ row: makeRow({ fullSyncState: 'ready', fullSyncLastRunAt: null }) });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('completed');
      expect(batchCommand.run).toHaveBeenCalledOnce();
    });

    it('skips from ready state when ran recently (within cooldown)', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand();
      const db = createMockDb({
        row: makeRow({ fullSyncState: 'ready', fullSyncLastRunAt: minutesAgo(2) }),
      });
      const command = createCommand({ batchCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'skipped', reason: 'ran-recently' });
      expect(batchCommand.run).not.toHaveBeenCalled();
    });

    it('proceeds from waiting-for-ingestion state', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const statsQuery = createMockGetScopeIngestionStatsQuery({ ok: true, inProgress: 5 });
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'waiting-for-ingestion',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, statsQuery, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('completed');
      expect(batchCommand.run).toHaveBeenCalledOnce();
    });

    it('skips from running state with fresh heartbeat', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand();
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'running',
          fullSyncHeartbeatAt: minutesAgo(5),
        }),
      });
      const command = createCommand({ batchCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'skipped', reason: 'already-running' });
      expect(batchCommand.run).not.toHaveBeenCalled();
    });

    it('proceeds from running state with stale heartbeat (recovery)', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'running',
          fullSyncHeartbeatAt: minutesAgo(25),
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('completed');
      expect(batchCommand.run).toHaveBeenCalledOnce();
    });

    it('proceeds from running state with null heartbeat (recovery)', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'running',
          fullSyncHeartbeatAt: null,
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('completed');
      expect(batchCommand.run).toHaveBeenCalledOnce();
    });

    it('proceeds from failed state', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({ fullSyncState: 'failed', fullSyncNextLink: 'https://graph.microsoft.com/next' }),
      });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('completed');
      expect(batchCommand.run).toHaveBeenCalledOnce();
    });

    it('skips from paused state', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand();
      const db = createMockDb({
        row: makeRow({ fullSyncState: 'paused' }),
      });
      const command = createCommand({ batchCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'skipped', reason: 'paused' });
      expect(batchCommand.run).not.toHaveBeenCalled();
    });

    it('skips when no inbox configuration exists', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand();
      const db = createMockDb({ row: undefined });
      const command = createCommand({ batchCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'skipped', reason: 'no-inbox-configuration' });
      expect(batchCommand.run).not.toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // Waiting-for-ingestion with scope stats
  // -------------------------------------------------------------------------

  describe('waiting-for-ingestion scope stats gating', () => {
    it('parks again when scope has >= 20 items in progress', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand();
      const statsQuery = createMockGetScopeIngestionStatsQuery({ ok: true, inProgress: 25 });
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'waiting-for-ingestion',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, statsQuery, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'waiting-for-ingestion' });
      expect(batchCommand.run).not.toHaveBeenCalled();
      expect(updateByVersionCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        expect.any(String),
        expect.objectContaining({ fullSyncState: 'waiting-for-ingestion' }),
      );
    });

    it('proceeds to batch when scope has < 20 items in progress', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const statsQuery = createMockGetScopeIngestionStatsQuery({ ok: true, inProgress: 15 });
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'waiting-for-ingestion',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, statsQuery, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('completed');
      expect(batchCommand.run).toHaveBeenCalledOnce();
    });

    it('proceeds optimistically when scope stats are unavailable', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const statsQuery = createMockGetScopeIngestionStatsQuery({ ok: false, inProgress: 0 });
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'waiting-for-ingestion',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, statsQuery, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('completed');
      expect(batchCommand.run).toHaveBeenCalledOnce();
    });

    it('returns skipped on version mismatch while parking for ingestion', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand();
      const statsQuery = createMockGetScopeIngestionStatsQuery({ ok: true, inProgress: 25 });
      const updateByVersionCommand = createMockUpdateByVersionCommand(false);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'waiting-for-ingestion',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, statsQuery, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'skipped', reason: 'version-mismatch' });
    });
  });

  // -------------------------------------------------------------------------
  // Fresh start behavior
  // -------------------------------------------------------------------------

  describe('fresh start', () => {
    it('fetches $count API on fresh start (null nextLink)', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(1000);
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({ fullSyncState: 'ready', fullSyncNextLink: null }),
      });
      const command = createCommand({ graphApi, batchCommand, updateByVersionCommand, db });

      await command.run(USER_PROFILE_ID);

      // updateByVersionCommand called: once for $count save, once for completion
      expect(updateByVersionCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        expect.any(String),
        expect.objectContaining({ fullSyncExpectedTotal: 1000 }),
      );
    });

    it('sets counters to 0 on fresh start via transaction update', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({ fullSyncState: 'ready', fullSyncNextLink: null }),
      });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      await command.run(USER_PROFILE_ID);

      // Verify the transaction update includes zero counters
      const txUpdate = db.__tx.update.mock.results[0]?.value;
      expect(txUpdate.set).toHaveBeenCalledWith(
        expect.objectContaining({
          fullSyncBatchIndex: 0,
          fullSyncSkipped: 0,
          fullSyncScheduledForIngestion: 0,
          fullSyncFailedToUploadForIngestion: 0,
          fullSyncNextLink: START_FULL_SYNC_LINK,
        }),
      );
    });

    it('does not fetch $count on resume (non-null nextLink)', async () => {
      const graphApi = createMockGraphApi();
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'ready',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
          fullSyncLastRunAt: null,
        }),
      });
      const command = createCommand({ graphApi, batchCommand, updateByVersionCommand, db });

      await command.run(USER_PROFILE_ID);

      // $count is only called on fresh starts; the graph API should not be called for $count
      // updateByVersionCommand should only be called for the completion update, not for $count
      const countCalls = updateByVersionCommand.run.mock.calls.filter((call: any[]) =>
        call[2] && 'fullSyncExpectedTotal' in call[2],
      );
      expect(countCalls).toHaveLength(0);
    });
  });

  // -------------------------------------------------------------------------
  // Batch result handling
  // -------------------------------------------------------------------------

  describe('batch result handling', () => {
    it('transitions to waiting-for-ingestion when batch is uploaded', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('batch-uploaded');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'ready',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'waiting-for-ingestion' });
      expect(updateByVersionCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        expect.any(String),
        expect.objectContaining({ fullSyncState: 'waiting-for-ingestion' }),
      );
    });

    it('returns version-mismatch when batch reports version-mismatch', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('version-mismatch');
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'ready',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'skipped', reason: 'version-mismatch' });
    });

    it('transitions to ready on completion', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'ready',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'completed' });
      expect(updateByVersionCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        expect.any(String),
        expect.objectContaining({
          fullSyncState: 'ready',
          fullSyncNextLink: null,
          fullSyncBatchIndex: 0,
        }),
      );
    });

    it('returns version-mismatch when completion update fails', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(false);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'ready',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'skipped', reason: 'version-mismatch' });
    });
  });

  // -------------------------------------------------------------------------
  // Error handling
  // -------------------------------------------------------------------------

  describe('error handling', () => {
    it('transitions to failed on batch processing error', async () => {
      const batchCommand = { run: vi.fn().mockRejectedValue(new Error('Batch failed')) };
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'ready',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('failed');
      expect(updateByVersionCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        expect.any(String),
        expect.objectContaining({ fullSyncState: 'failed' }),
      );
    });

    it('does not throw when $count API fails', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockRejectedValue(new Error('$count failed'));
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({ fullSyncState: 'ready', fullSyncNextLink: null }),
      });
      const command = createCommand({ graphApi, batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('completed');
    });
  });
});
