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

function makeEmail(id: string, created: string, modified: string) {
  return {
    id,
    internetMessageId: `<${id}@example.com>`,
    createdDateTime: created,
    lastModifiedDateTime: modified,
    from: { emailAddress: { address: 'sender@example.com', name: 'Sender' } },
    subject: `Email ${id}`,
    uniqueBody: { contentType: 'text' as const, content: `Body of ${id}` },
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

function createMockAmqp() {
  return { publish: vi.fn().mockResolvedValue(undefined) };
}

/**
 * Creates a mock DB that supports:
 * - `db.query.subscriptions.findFirst()` for subscription lookup
 * - `db.transaction(cb)` with a mock tx supporting select...from...where...for('update')...then()
 * - `db.update().set().where().execute()` for state transitions and watermark updates
 *
 * The `db.transaction` mock handles two calls: the first uses `lockResult` for the
 * acquireLock transaction, and the second uses `flushResult` for flushPendingMessages.
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
    filters: Record<string, unknown>;
    pendingLiveMessageIds: string[];
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
  amqp,
  db,
  syncDirectories,
}: {
  graphApi: ReturnType<typeof createMockGraphApi>;
  amqp: ReturnType<typeof createMockAmqp>;
  syncDirectories: ReturnType<typeof createMockSyncDirectoriesCommand>;
  db: ReturnType<typeof createMockDb>;
}): LiveCatchUpCommand {
  return new LiveCatchUpCommand(
    createMockGraphClientFactory(graphApi) as any,
    amqp as any,
    syncDirectories as any,
    db as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LiveCatchUpCommand', () => {
  let graphApi: ReturnType<typeof createMockGraphApi>;
  let amqp: ReturnType<typeof createMockAmqp>;
  let syncDirectories: ReturnType<typeof createMockSyncDirectoriesCommand>;

  beforeEach(() => {
    graphApi = createMockGraphApi();
    amqp = createMockAmqp();
    syncDirectories = createMockSyncDirectoriesCommand();
    vi.clearAllMocks();
  });

  it('skips when subscription is not found', async () => {
    const db = createMockDb({ subscription: undefined, lockResult: undefined });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(db.transaction).not.toHaveBeenCalled();
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('skips when lock is already held (liveCatchUpState is running)', async () => {
    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'running',
        newestLastModifiedDateTime: WATERMARK,
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // Transaction was called (to attempt lock), but no graph call made
    expect(db.transaction).toHaveBeenCalled();
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('skips when no watermark exists (full sync not started)', async () => {
    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: null,
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(db.transaction).toHaveBeenCalled();
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('skips when inbox config row is missing inside transaction', async () => {
    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: undefined, // no rows returned from FOR UPDATE
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(db.transaction).toHaveBeenCalled();
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('fetches a batch and sets state to ready', async () => {
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
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // Both emails published
    expect(amqp.publish).toHaveBeenCalledTimes(2);

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
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(amqp.publish).toHaveBeenCalledTimes(2);
    expect(graphApi.get).toHaveBeenCalledTimes(2);
  });

  it('deduplicates webhook messageIds covered by batching', async () => {
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
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
      // acquireLock stores all 3 webhook IDs in pendingLiveMessageIds;
      // flush reads them back and publishes only msg-3 (msg-1 & msg-2 are in scheduledIds)
      flushResult: { pendingLiveMessageIds: ['msg-1', 'msg-2', 'msg-3'] },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    // msg-1 and msg-2 are in the batch, msg-3 is webhook-only
    await command.run({
      subscriptionId: SUBSCRIPTION_ID,
      messageIds: ['msg-1', 'msg-2', 'msg-3'],
    });

    // 2 from batch + 1 remaining webhook ID = 3 total publishes
    expect(amqp.publish).toHaveBeenCalledTimes(3);

    // Verify the webhook-only ID was published
    const publishedMessageIds = amqp.publish.mock.calls.map((call: any[]) => {
      const event = call[2] as { payload: { messageId: string } };
      return event.payload.messageId;
    });
    expect(publishedMessageIds).toContain('msg-3');
  });

  it('publishes remaining webhook IDs not covered by batching', async () => {
    // Empty batch — no emails from Graph
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
      // acquireLock stores the webhook IDs in pendingLiveMessageIds;
      // flush publishes both since the batch scheduled nothing
      flushResult: { pendingLiveMessageIds: ['webhook-1', 'webhook-2'] },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({
      subscriptionId: SUBSCRIPTION_ID,
      messageIds: ['webhook-1', 'webhook-2'],
    });

    // Only the 2 webhook IDs should be published
    expect(amqp.publish).toHaveBeenCalledTimes(2);
    const publishedMessageIds = amqp.publish.mock.calls.map((call: any[]) => {
      const event = call[2] as { payload: { messageId: string } };
      return event.payload.messageId;
    });
    expect(publishedMessageIds).toEqual(['webhook-1', 'webhook-2']);
  });

  it('does not double-publish when all webhook IDs are covered by batch', async () => {
    const emails = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({
      subscriptionId: SUBSCRIPTION_ID,
      messageIds: ['msg-1'],
    });

    // Only 1 publish from the batch — webhook msg-1 is deduplicated
    expect(amqp.publish).toHaveBeenCalledTimes(1);
  });

  it('sets state to failed on error', async () => {
    graphApi.get.mockRejectedValueOnce(new Error('Graph API error'));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    // Should NOT throw
    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // State set to 'failed'
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
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(graphApi.filter).toHaveBeenCalledWith(
      `lastModifiedDateTime ge ${WATERMARK.toISOString()}`,
    );
  });

  // ---------------------------------------------------------------------------
  // Live catch-up buffering
  // ---------------------------------------------------------------------------

  it('buffers message IDs when live catch-up is already running', async () => {
    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'running',
        newestLastModifiedDateTime: WATERMARK,
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({
      subscriptionId: SUBSCRIPTION_ID,
      messageIds: ['msg-a', 'msg-b'],
    });

    // The array_cat update was called inside the lock transaction
    expect(db.__lockTx.update).toHaveBeenCalled();
    expect(db.__lockTx.__txUpdate.set).toHaveBeenCalled();

    // No graph call or publish — returns early after buffering
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('does not re-publish pending messages already covered by the batch', async () => {
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
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
      // msg-1 was previously buffered in pendingLiveMessageIds; the batch covers it,
      // so flush deduplicates it (alreadyScheduledIds contains msg-1 and msg-2)
      flushResult: { pendingLiveMessageIds: ['msg-1'] },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // Batch publishes both msg-1 and msg-2; flush skips msg-1 (already scheduled)
    const publishedMessageIds = amqp.publish.mock.calls.map((call: any[]) => {
      const event = call[2] as { payload: { messageId: string } };
      return event.payload.messageId;
    });
    expect(publishedMessageIds).toHaveLength(2);
    expect(publishedMessageIds).toContain('msg-1');
    expect(publishedMessageIds).toContain('msg-2');
    // msg-1 published exactly once — not re-published from flush
    expect(publishedMessageIds.filter((id: string) => id === 'msg-1')).toHaveLength(1);
  });

  it('flushes pending messages not already scheduled', async () => {
    const emails = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
      flushResult: { pendingLiveMessageIds: ['flush-1', 'flush-2'] },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // msg-1 from batch + flush-1 and flush-2 from pending flush = 3 publishes
    expect(amqp.publish).toHaveBeenCalledTimes(3);
    const publishedMessageIds = amqp.publish.mock.calls.map((call: any[]) => {
      const event = call[2] as { payload: { messageId: string } };
      return event.payload.messageId;
    });
    expect(publishedMessageIds).toEqual(['msg-1', 'flush-1', 'flush-2']);

    // Flush transaction clears pendingLiveMessageIds and sets state to ready
    expect(db.__flushTx.__txUpdate.set).toHaveBeenCalledWith(
      expect.objectContaining({ pendingLiveMessageIds: [], liveCatchUpState: 'ready' }),
    );
  });

  it('flush skips IDs already scheduled during the run', async () => {
    const emails = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
      flushResult: { pendingLiveMessageIds: ['msg-1', 'flush-1'] },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // msg-1 from batch + flush-1 from flush (msg-1 not re-published by flush) = 2 publishes
    expect(amqp.publish).toHaveBeenCalledTimes(2);
    const publishedMessageIds = amqp.publish.mock.calls.map((call: any[]) => {
      const event = call[2] as { payload: { messageId: string } };
      return event.payload.messageId;
    });
    expect(publishedMessageIds).toEqual(['msg-1', 'flush-1']);
  });

  it('flush is a no-op when no pending IDs exist', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
        filters: DEFAULT_FILTERS,
        pendingLiveMessageIds: [],
      },
      flushResult: { pendingLiveMessageIds: [] },
    });
    const command = createCommand({ graphApi, amqp, db, syncDirectories });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // No publishes at all — empty batch and empty pending
    expect(amqp.publish).not.toHaveBeenCalled();

    // State still set to ready via flush transaction
    expect(db.__flushTx.__txUpdate.set).toHaveBeenCalledWith(
      expect.objectContaining({ liveCatchUpState: 'ready' }),
    );
  });
});
