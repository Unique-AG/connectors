/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveCatchUpCommand, READY_LIVE_CATCHUP_THRESHOLD_MINUTES, STUCK_LIVE_CATCHUP_THRESHOLD_MINUTES } from './live-catch-up.command';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SUBSCRIPTION_ID = 'sub-001';
const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const WATERMARK = new Date('2024-06-01T00:00:00Z');
const IGNORED_BEFORE = '2024-01-01T00:00:00.000Z';
const DEFAULT_FILTERS = { ignoredBefore: IGNORED_BEFORE, ignoredSenders: [], ignoredContents: [] };

// A recent heartbeat (within all cooldown windows)
const RECENT_HEARTBEAT = new Date(Date.now() - 1 * 60 * 1000); // 1 minute ago
// A stale heartbeat (older than all cooldown thresholds)
const STALE_HEARTBEAT = new Date(Date.now() - 999 * 60 * 1000); // ~16 hours ago

function makeEmail(id: string, created: string, modified: string) {
  return {
    id,
    createdDateTime: created,
    lastModifiedDateTime: modified,
  };
}

function makeGraphResponse(emails: ReturnType<typeof makeEmail>[], nextLink?: string) {
  return {
    value: emails,
    ...(nextLink ? { '@odata.nextLink': nextLink } : {}),
  };
}

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function createMockGraphApi() {
  const api: Record<string, any> = {
    header: vi.fn().mockReturnThis(),
    select: vi.fn().mockReturnThis(),
    filter: vi.fn().mockReturnThis(),
    orderby: vi.fn().mockReturnThis(),
    top: vi.fn().mockReturnThis(),
    get: vi.fn(),
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

function createMockIngestEmailCommand() {
  return { run: vi.fn().mockResolvedValue('ingested') };
}

/**
 * Creates a mock DB that supports:
 * - `db.query.subscriptions.findFirst()` for subscription lookup
 * - `db.transaction(cb)` — first call uses lockResult (acquireLock), second uses flushResult (flushPendingMessages)
 * - `db.update().set().where().execute()` for watermark updates and state transitions
 */
function createMockDb({
  subscription,
  lockResult,
  flushResult,
}: {
  subscription?: { userProfileId: string } | undefined;
  lockResult?: {
    liveCatchUpState: string;
    newestLastModifiedDateTime: Date | null;
    liveCatchUpHeartbeatAt: Date | null;
    filters: Record<string, unknown>;
  };
  flushResult?: { pendingLiveMessageIds: string[] };
}) {
  let transactionCallCount = 0;

  function createMockTx(selectRows: any[]) {
    const txExecuteFn = vi.fn().mockResolvedValue(undefined);
    const txSelect = {
      from: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          for: vi.fn().mockResolvedValue(selectRows),
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
    return {
      select: vi.fn().mockReturnValue(txSelect),
      update: vi.fn().mockReturnValue(txUpdate),
      __txExecuteFn: txExecuteFn,
      __txUpdate: txUpdate,
    };
  }

  const lockTx = createMockTx(lockResult ? [lockResult] : []);
  const flushTx = createMockTx(flushResult ? [flushResult] : [{ pendingLiveMessageIds: [] }]);

  const dbExecuteFn = vi.fn().mockResolvedValue(undefined);
  const db = {
    query: {
      subscriptions: {
        findFirst: vi.fn().mockResolvedValue(subscription),
      },
    },
    transaction: vi.fn(async (cb: (tx: any) => Promise<any>) => {
      transactionCallCount++;
      if (transactionCallCount === 1) {
        return cb(lockTx);
      }
      return cb(flushTx);
    }),
    update: vi.fn().mockReturnValue({
      set: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          execute: dbExecuteFn,
        }),
      }),
    }),
    __lockTx: lockTx,
    __flushTx: flushTx,
    __dbExecuteFn: dbExecuteFn,
  };

  return db;
}

function createMockSyncDirectoriesCommand() {
  return { run: vi.fn() };
}

function createCommand({
  graphApi,
  ingestEmailCommand,
  db,
  syncDirectories,
}: {
  graphApi: ReturnType<typeof createMockGraphApi>;
  ingestEmailCommand: ReturnType<typeof createMockIngestEmailCommand>;
  syncDirectories: ReturnType<typeof createMockSyncDirectoriesCommand>;
  db: ReturnType<typeof createMockDb>;
}): LiveCatchUpCommand {
  return new LiveCatchUpCommand(
    createMockGraphClientFactory(graphApi) as any,
    ingestEmailCommand as any,
    syncDirectories as any,
    db as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LiveCatchUpCommand', () => {
  let graphApi: ReturnType<typeof createMockGraphApi>;
  let ingestEmailCommand: ReturnType<typeof createMockIngestEmailCommand>;
  let syncDirectories: ReturnType<typeof createMockSyncDirectoriesCommand>;

  beforeEach(() => {
    graphApi = createMockGraphApi();
    ingestEmailCommand = createMockIngestEmailCommand();
    syncDirectories = createMockSyncDirectoriesCommand();
    vi.clearAllMocks();
  });

  it('skips when subscription is not found', async () => {
    const db = createMockDb({ subscription: undefined, lockResult: undefined });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(db.transaction).not.toHaveBeenCalled();
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();
  });

  it('skips when lock is already running with recent heartbeat', async () => {
    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'running',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: RECENT_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(db.transaction).toHaveBeenCalled();
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();
  });

  it('proceeds when lock is running with stale heartbeat (stuck recovery)', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'running',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // Proceeded — graph was queried
    expect(graphApi.get).toHaveBeenCalled();
  });

  it('skips when ready with recent heartbeat (cooldown)', async () => {
    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: RECENT_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(graphApi.get).not.toHaveBeenCalled();
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();
  });

  it('proceeds when ready with stale heartbeat', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(graphApi.get).toHaveBeenCalled();
  });

  it('always proceeds when state is failed', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'failed',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: RECENT_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // Proceeded despite recent heartbeat — failed state always proceeds
    expect(graphApi.get).toHaveBeenCalled();
  });

  it('skips when no watermark exists (full sync not started)', async () => {
    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: null,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(db.transaction).toHaveBeenCalled();
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();
  });

  it('skips when inbox config row is missing inside transaction', async () => {
    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: undefined,
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(db.transaction).toHaveBeenCalled();
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();
  });

  it('calls ingestEmailCommand.run for each fetched email', async () => {
    const emails = [
      makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z'),
      makeEmail('msg-2', '2024-06-02T00:00:00Z', '2024-06-02T01:00:00Z'),
    ];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(2);
    expect(ingestEmailCommand.run).toHaveBeenCalledWith(
      expect.objectContaining({ userProfileId: USER_PROFILE_ID, messageId: 'msg-1' }),
    );
    expect(ingestEmailCommand.run).toHaveBeenCalledWith(
      expect.objectContaining({ userProfileId: USER_PROFILE_ID, messageId: 'msg-2' }),
    );

    // State set to 'ready' via flush transaction
    const flushUpdate = db.__flushTx.__txUpdate;
    expect(flushUpdate.set).toHaveBeenCalledWith(
      expect.objectContaining({ liveCatchUpState: 'ready' }),
    );
  });

  it('follows nextLink to fetch multiple batches', async () => {
    const batch1 = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    const batch2 = [makeEmail('msg-2', '2024-06-02T00:00:00Z', '2024-06-02T01:00:00Z')];

    graphApi.get
      .mockResolvedValueOnce(makeGraphResponse(batch1, 'https://graph.microsoft.com/nextPage'))
      .mockResolvedValueOnce(makeGraphResponse(batch2));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(2);
    expect(graphApi.get).toHaveBeenCalledTimes(2);
  });

  it('continues processing when ingestEmailCommand.run returns failed', async () => {
    const emails = [
      makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z'),
      makeEmail('msg-2', '2024-06-02T00:00:00Z', '2024-06-02T01:00:00Z'),
    ];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));
    ingestEmailCommand.run
      .mockResolvedValueOnce('failed')   // msg-1 fails
      .mockResolvedValueOnce('ingested'); // msg-2 succeeds

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    // Should NOT throw
    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // Both emails were attempted
    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(2);
  });

  it('deduplicates webhook messageIds covered by batch processing', async () => {
    const emails = [
      makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z'),
      makeEmail('msg-2', '2024-06-02T00:00:00Z', '2024-06-02T01:00:00Z'),
    ];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
      // flush returns msg-1, msg-2, msg-3 as pending; msg-1 and msg-2 are in processedIds so only msg-3 is flushed
      flushResult: { pendingLiveMessageIds: ['msg-1', 'msg-2', 'msg-3'] },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({
      subscriptionId: SUBSCRIPTION_ID,
      messageIds: ['msg-1', 'msg-2', 'msg-3'],
    });

    // 2 from batch + 1 from flush = 3 total ingest calls
    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(3);
    const ingestedIds = ingestEmailCommand.run.mock.calls.map((call: any[]) => call[0].messageId);
    expect(ingestedIds).toContain('msg-3');
  });

  it('ingests remaining pending IDs not covered by batch', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
      flushResult: { pendingLiveMessageIds: ['webhook-1', 'webhook-2'] },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({
      subscriptionId: SUBSCRIPTION_ID,
      messageIds: ['webhook-1', 'webhook-2'],
    });

    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(2);
    const ingestedIds = ingestEmailCommand.run.mock.calls.map((call: any[]) => call[0].messageId);
    expect(ingestedIds).toEqual(['webhook-1', 'webhook-2']);
  });

  it('does not double-ingest when all webhook IDs are covered by batch', async () => {
    const emails = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({
      subscriptionId: SUBSCRIPTION_ID,
      messageIds: ['msg-1'],
    });

    // Only 1 ingest call — webhook msg-1 is deduplicated
    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(1);
  });

  it('sets state to failed on error', async () => {
    graphApi.get.mockRejectedValueOnce(new Error('Graph API error'));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    // Should NOT throw
    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    const lastUpdateSetCall = db.update.mock.results[db.update.mock.calls.length - 1]?.value.set;
    expect(lastUpdateSetCall).toHaveBeenCalledWith(
      expect.objectContaining({ liveCatchUpState: 'failed' }),
    );
  });

  it('uses the watermark in the filter expression', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(graphApi.filter).toHaveBeenCalledWith(
      `lastModifiedDateTime ge ${WATERMARK.toISOString()}`,
    );
  });

  it('buffers message IDs when live catch-up is already running with recent heartbeat', async () => {
    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'running',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: RECENT_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({
      subscriptionId: SUBSCRIPTION_ID,
      messageIds: ['msg-a', 'msg-b'],
    });

    // The array_cat update was called inside the lock transaction
    expect(db.__lockTx.update).toHaveBeenCalled();
    expect(db.__lockTx.__txUpdate.set).toHaveBeenCalled();

    // No graph call or ingest — returns early after buffering
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();
  });

  it('does not re-ingest pending messages already covered by the batch', async () => {
    const emails = [
      makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z'),
      makeEmail('msg-2', '2024-06-02T00:00:00Z', '2024-06-02T01:00:00Z'),
    ];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
      // msg-1 was previously buffered; the batch covers it, so flush deduplicates it
      flushResult: { pendingLiveMessageIds: ['msg-1'] },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // Batch ingests msg-1 and msg-2; flush skips msg-1 (already processed)
    const ingestedIds = ingestEmailCommand.run.mock.calls.map((call: any[]) => call[0].messageId);
    expect(ingestedIds).toHaveLength(2);
    expect(ingestedIds).toContain('msg-1');
    expect(ingestedIds).toContain('msg-2');
    // msg-1 ingested exactly once
    expect(ingestedIds.filter((id: string) => id === 'msg-1')).toHaveLength(1);
  });

  it('flushes pending messages not already processed', async () => {
    const emails = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
      flushResult: { pendingLiveMessageIds: ['flush-1', 'flush-2'] },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // msg-1 from batch + flush-1 and flush-2 from pending flush = 3 ingest calls
    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(3);
    const ingestedIds = ingestEmailCommand.run.mock.calls.map((call: any[]) => call[0].messageId);
    expect(ingestedIds).toEqual(['msg-1', 'flush-1', 'flush-2']);

    // Flush transaction clears pendingLiveMessageIds and sets state to ready
    expect(db.__flushTx.__txUpdate.set).toHaveBeenCalledWith(
      expect.objectContaining({ pendingLiveMessageIds: [], liveCatchUpState: 'ready' }),
    );
  });

  it('flush skips IDs already processed during the run', async () => {
    const emails = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
      flushResult: { pendingLiveMessageIds: ['msg-1', 'flush-1'] },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // msg-1 from batch + flush-1 from flush (msg-1 not re-ingested) = 2 ingest calls
    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(2);
    const ingestedIds = ingestEmailCommand.run.mock.calls.map((call: any[]) => call[0].messageId);
    expect(ingestedIds).toEqual(['msg-1', 'flush-1']);
  });

  it('flush is a no-op when no pending IDs exist', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
      flushResult: { pendingLiveMessageIds: [] },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // No ingest calls at all
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();

    // State still set to ready via flush transaction
    expect(db.__flushTx.__txUpdate.set).toHaveBeenCalledWith(
      expect.objectContaining({ liveCatchUpState: 'ready' }),
    );
  });

  it('continues flush ingestion even when an individual message fails', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));
    ingestEmailCommand.run
      .mockResolvedValueOnce('failed')   // webhook-1 fails in flush
      .mockResolvedValueOnce('ingested'); // webhook-2 succeeds

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
      flushResult: { pendingLiveMessageIds: ['webhook-1', 'webhook-2'] },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // Both were attempted despite the first failing
    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(2);
  });
});
