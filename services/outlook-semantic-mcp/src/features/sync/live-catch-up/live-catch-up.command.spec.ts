/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveCatchUpCommand } from './live-catch-up.command';

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
    receivedDateTime: created,
    parentFolderId: 'folder-id',
    webLink: 'https://outlook.office.com/mail/id',
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

function createMockUniqueApi() {
  return {
    files: { getByKeys: vi.fn().mockResolvedValue([]) },
  };
}

/**
 * Creates a mock DB that supports:
 * - `db.select().from().innerJoin().then()` for user profile lookup
 * - `db.transaction(cb)` for acquireLock
 * - `db.update().set().where().execute()` for watermark updates and state transitions
 */
function createMockDb({
  subscription,
  lockResult,
}: {
  subscription?: { userProfileId: string; userEmail: string; providerUserId: string } | undefined;
  lockResult?: {
    liveCatchUpState: string;
    newestLastModifiedDateTime: Date | null;
    liveCatchUpHeartbeatAt: Date | null;
    filters: Record<string, unknown>;
  };
}) {
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

  const dbExecuteFn = vi.fn().mockResolvedValue(undefined);
  const db = {
    select: vi.fn().mockReturnValue({
      from: vi.fn().mockReturnValue({
        innerJoin: vi.fn().mockReturnValue({
          where: vi.fn().mockResolvedValue(subscription ? [subscription] : []),
        }),
      }),
    }),
    transaction: vi.fn(async (cb: (tx: any) => Promise<any>) => cb(lockTx)),
    update: vi.fn().mockReturnValue({
      set: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          execute: dbExecuteFn,
        }),
      }),
    }),
    __lockTx: lockTx,
    __dbExecuteFn: dbExecuteFn,
  };

  return db;
}

function createMockSyncDirectoriesCommand() {
  return { run: vi.fn() };
}

function createMockMetricService() {
  return { getCounter: vi.fn().mockReturnValue({ add: vi.fn() }) };
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
    createMockUniqueApi() as any,
    db as any,
    createMockMetricService() as any,
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

    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

    expect(db.transaction).not.toHaveBeenCalled();
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();
  });

  it('skips when lock is already running with recent heartbeat', async () => {
    const db = createMockDb({
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: {
        liveCatchUpState: 'running',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: RECENT_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

    expect(db.transaction).toHaveBeenCalled();
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();
  });

  it('proceeds when lock is running with stale heartbeat (stuck recovery)', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: {
        liveCatchUpState: 'running',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

    // Proceeded — graph was queried
    expect(graphApi.get).toHaveBeenCalled();
  });

  it('runs when ready with recent heartbeat', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: RECENT_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

    expect(graphApi.get).toHaveBeenCalled();
  });

  it('proceeds when ready with stale heartbeat', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

    expect(graphApi.get).toHaveBeenCalled();
  });

  it('always proceeds when state is failed', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: {
        liveCatchUpState: 'failed',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: RECENT_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

    // Proceeded despite recent heartbeat — failed state always proceeds
    expect(graphApi.get).toHaveBeenCalled();
  });

  it('skips when inbox config row is missing inside transaction', async () => {
    const db = createMockDb({
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: undefined,
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

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
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(2);
    expect(ingestEmailCommand.run).toHaveBeenCalledWith(
      expect.objectContaining({
        graphMessage: expect.objectContaining({ id: 'msg-1' }),
        user: expect.objectContaining({ profileId: USER_PROFILE_ID }),
      }),
    );
    expect(ingestEmailCommand.run).toHaveBeenCalledWith(
      expect.objectContaining({
        graphMessage: expect.objectContaining({ id: 'msg-2' }),
      }),
    );

    // State set to 'ready'
    const setMock = db.update.mock.results[0]?.value?.set;
    expect(setMock).toHaveBeenCalledWith(expect.objectContaining({ liveCatchUpState: 'ready' }));
  });

  it('follows nextLink to fetch multiple batches', async () => {
    const batch1 = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    const batch2 = [makeEmail('msg-2', '2024-06-02T00:00:00Z', '2024-06-02T01:00:00Z')];

    graphApi.get
      .mockResolvedValueOnce(makeGraphResponse(batch1, 'https://graph.microsoft.com/nextPage'))
      .mockResolvedValueOnce(makeGraphResponse(batch2));

    const db = createMockDb({
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

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
      .mockResolvedValueOnce('failed') // msg-1 fails
      .mockResolvedValueOnce('ingested'); // msg-2 succeeds

    const db = createMockDb({
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    // Should NOT throw
    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

    // Both emails were attempted
    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(2);
  });

  it('sets state to failed on error', async () => {
    graphApi.get.mockRejectedValueOnce(new Error('Graph API error'));

    const db = createMockDb({
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    // Should NOT throw
    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

    const lastUpdateSetCall = db.update.mock.results[db.update.mock.calls.length - 1]?.value.set;
    expect(lastUpdateSetCall).toHaveBeenCalledWith(
      expect.objectContaining({ liveCatchUpState: 'failed' }),
    );
  });

  it('uses the watermark in the filter expression', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: {
        userProfileId: USER_PROFILE_ID,
        userEmail: 'user@example.com',
        providerUserId: 'provider-id',
      },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        liveCatchUpHeartbeatAt: STALE_HEARTBEAT,
        filters: DEFAULT_FILTERS,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, liveCatchupOverlappingWindow: 5 });

    expect(graphApi.filter).toHaveBeenCalledWith(
      `lastModifiedDateTime ge ${WATERMARK.toISOString()}`,
    );
  });
});
