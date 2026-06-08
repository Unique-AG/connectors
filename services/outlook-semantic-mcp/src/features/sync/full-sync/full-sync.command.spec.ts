/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FullSyncCommand, START_FULL_SYNC_LINK } from './full-sync.command';

vi.mock('~/features/tracing.utils', () => ({
  traceAttrs: vi.fn(),
  traceEvent: vi.fn(),
  NewTrace: () => () => ({}),
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
    filter: vi.fn().mockReturnThis(),
    get: vi.fn().mockResolvedValue(42),
  };
  return api;
}

function createMockMsGraphClientResolver(graphApi: ReturnType<typeof createMockGraphApi>) {
  const mockClient = { api: vi.fn().mockReturnValue(graphApi) };
  return {
    run: vi
      .fn()
      .mockImplementation(
        async ({
          fn,
        }: {
          fn: (ctx: { client: any; clientUserProfileId: string }) => Promise<any>;
        }) => fn({ client: mockClient, clientUserProfileId: 'delegate-profile-id' }),
      ),
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
function createSyncDirectoriesVersionCommand() {
  return { run: vi.fn() };
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
    filters: Record<string, unknown>;
    preferredDelegateUserProfileId?: string | null;
    deletingInboxStartedAt?: Date | null;
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

  const topLevelUpdate = {
    set: vi.fn().mockReturnValue({
      where: vi.fn().mockReturnValue({
        execute: vi.fn().mockResolvedValue(undefined),
      }),
    }),
  };

  return {
    transaction: vi.fn(async (cb: (tx: any) => Promise<any>) => cb(tx)),
    update: vi.fn().mockReturnValue(topLevelUpdate),
    query: {
      userProfiles: {
        findFirst: vi.fn().mockResolvedValue({
          id: USER_PROFILE_ID,
          email: 'test@example.com',
          providerUserId: null,
          source: 'oauth',
        }),
      },
    },
    __tx: tx,
  };
}

function createCommand({
  graphApi = createMockGraphApi(),
  batchCommand = createMockProcessFullSyncBatchCommand(),
  statsQuery = createMockGetScopeIngestionStatsQuery(),
  updateByVersionCommand = createMockUpdateByVersionCommand(),
  db = createMockDb({ row: undefined }),
  syncDirectories = createSyncDirectoriesVersionCommand(),
}: {
  graphApi?: ReturnType<typeof createMockGraphApi>;
  batchCommand?: ReturnType<typeof createMockProcessFullSyncBatchCommand>;
  statsQuery?: ReturnType<typeof createMockGetScopeIngestionStatsQuery>;
  updateByVersionCommand?: ReturnType<typeof createMockUpdateByVersionCommand>;
  db?: ReturnType<typeof createMockDb>;
  syncDirectories?: ReturnType<typeof createSyncDirectoriesVersionCommand>;
} = {}): FullSyncCommand {
  return new FullSyncCommand(
    createMockMsGraphClientResolver(graphApi) as any,
    batchCommand as any,
    statsQuery as any,
    updateByVersionCommand as any,
    syncDirectories as any,
    { run: vi.fn().mockResolvedValue(false) } as any,
    { mcpBackend: 'microsoft_graph_and_unique_api' } as any,
    db as any,
    {
      measureFullSyncRun: vi.fn().mockImplementation((fn: () => Promise<unknown>) => fn()),
      measureFullSyncDirectorySync: vi
        .fn()
        .mockImplementation((fn: () => Promise<unknown>) => fn()),
      measureFullSyncBatch: vi.fn().mockImplementation((fn: () => Promise<unknown>) => fn()),
    } as any,
  );
}

function makeRow(
  overrides: Partial<{
    fullSyncState: string;
    fullSyncVersion: string | null;
    fullSyncNextLink: string | null;
    fullSyncHeartbeatAt: Date | null;
    fullSyncLastRunAt: Date | null;
    fullSyncExpectedTotal: number | null;
    newestLastModifiedDateTime: Date | null;
    filters: Record<string, unknown>;
    deletingInboxStartedAt: Date | null;
    preferredDelegateUserProfileId: string | null;
  }> = {},
) {
  return {
    fullSyncState: 'ready' as string,
    fullSyncVersion: 'v1',
    fullSyncNextLink: null as string | null,
    fullSyncHeartbeatAt: null as Date | null,
    fullSyncLastRunAt: null as Date | null,
    fullSyncExpectedTotal: null as number | null,
    newestLastModifiedDateTime: null as Date | null,
    filters: { retentionWindowInDays: 95 } as Record<string, unknown>,
    deletingInboxStartedAt: null as Date | null,
    preferredDelegateUserProfileId: null as string | null,
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
      const db = createMockDb({
        row: makeRow({ fullSyncState: 'ready', fullSyncLastRunAt: null }),
      });
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

    it('proceeds from failed state with stale heartbeat', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'failed',
          fullSyncHeartbeatAt: minutesAgo(25),
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('completed');
      expect(batchCommand.run).toHaveBeenCalledOnce();
    });

    it('skips from failed state when heartbeat is within cooldown', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand();
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'failed',
          fullSyncHeartbeatAt: minutesAgo(5),
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      const command = createCommand({ batchCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'skipped', reason: 'recovery-retried-to-early' });
      expect(batchCommand.run).not.toHaveBeenCalled();
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

    it('skips when inbox deletion is in progress', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand();
      const db = createMockDb({
        row: makeRow({ deletingInboxStartedAt: new Date() }),
      });
      const command = createCommand({ batchCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'skipped', reason: 'inbox-deletion-in-progress' });
      expect(batchCommand.run).not.toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // Waiting-for-ingestion with scope stats
  // -------------------------------------------------------------------------

  describe('waiting-for-ingestion scope stats gating', () => {
    it('parks again when scope has >= 10 items in progress', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand();
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

      expect(result).toEqual({ status: 'waiting-for-ingestion' });
      expect(batchCommand.run).not.toHaveBeenCalled();
      expect(updateByVersionCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        expect.any(String),
        expect.objectContaining({ fullSyncState: 'waiting-for-ingestion' }),
      );
    });

    it('proceeds to batch when scope has < 10 items in progress', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const statsQuery = createMockGetScopeIngestionStatsQuery({ ok: true, inProgress: 5 });
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

    it('waits for ingestion optimistically when scope stats are unavailable', async () => {
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

      expect(result.status).toBe('waiting-for-ingestion');
      expect(batchCommand.run).not.toHaveBeenCalled();
    });

    it('returns skipped on version mismatch while waiting for ingestion', async () => {
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

    it('does fetch $count on resume if count is nullish (non-null nextLink)', async () => {
      const graphApi = createMockGraphApi();
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'ready',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
          fullSyncLastRunAt: null,
          fullSyncExpectedTotal: null,
        }),
      });
      const command = createCommand({ graphApi, batchCommand, updateByVersionCommand, db });

      await command.run(USER_PROFILE_ID);

      // $count is only called on fresh starts; the graph API should not be called for $count
      // updateByVersionCommand should only be called for the completion update, not for $count
      const countCalls = updateByVersionCommand.run.mock.calls.filter(
        (call: any[]) => call[2] && 'fullSyncExpectedTotal' in call[2],
      );
      expect(countCalls).toHaveLength(1);
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

  // -------------------------------------------------------------------------
  // Shared-mailbox delegate persistence
  // -------------------------------------------------------------------------

  describe('shared-mailbox delegate persistence', () => {
    it('persists preferredDelegateUserProfileId after a successful resolver call', async () => {
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'ready',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      db.query.userProfiles.findFirst.mockResolvedValue({
        id: USER_PROFILE_ID,
        email: 'shared@example.com',
        providerUserId: null,
        source: 'shared-mailbox',
      });
      const command = createCommand({ batchCommand, updateByVersionCommand, db });

      const result = await command.run(USER_PROFILE_ID);

      expect(result.status).toBe('completed');
      expect(db.update).toHaveBeenCalled();
      const topLevelUpdate = db.update.mock.results[0]?.value;
      expect(topLevelUpdate.set).toHaveBeenCalledWith(
        expect.objectContaining({ preferredDelegateUserProfileId: 'delegate-profile-id' }),
      );
    });

    it('returns failed with reason no-delegates and transitions state to failed when resolver returns NO_DELEGATES', async () => {
      const { NO_DELEGATES } = await import('~/msgraph/ms-graph-client-resolver.service');
      const batchCommand = createMockProcessFullSyncBatchCommand('completed');
      const updateByVersionCommand = createMockUpdateByVersionCommand(true);
      const db = createMockDb({
        row: makeRow({
          fullSyncState: 'ready',
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      });
      db.query.userProfiles.findFirst.mockResolvedValue({
        id: USER_PROFILE_ID,
        email: 'shared@example.com',
        providerUserId: null,
        source: 'shared-mailbox',
      });
      const noDelegatesResolver = {
        run: vi.fn().mockResolvedValue(NO_DELEGATES),
      };
      const command = new FullSyncCommand(
        noDelegatesResolver as any,
        batchCommand as any,
        createMockGetScopeIngestionStatsQuery() as any,
        updateByVersionCommand as any,
        createSyncDirectoriesVersionCommand() as any,
        { run: vi.fn().mockResolvedValue(false) } as any,
        { mcpBackend: 'microsoft_graph_and_unique_api' } as any,
        db as any,
        {
          measureFullSyncRun: vi.fn().mockImplementation((fn: () => Promise<unknown>) => fn()),
          measureFullSyncDirectorySync: vi
            .fn()
            .mockImplementation((fn: () => Promise<unknown>) => fn()),
          measureFullSyncBatch: vi.fn().mockImplementation((fn: () => Promise<unknown>) => fn()),
        } as any,
      );

      const result = await command.run(USER_PROFILE_ID);

      expect(result).toEqual({ status: 'failed-no-delegates' });
      expect(updateByVersionCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        expect.any(String),
        expect.objectContaining({ fullSyncState: 'failed' }),
      );
      expect(db.update).not.toHaveBeenCalled();
    });
  });
});
