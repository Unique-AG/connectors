/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveCatchUpCommand } from './live-catch-up.command';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SUBSCRIPTION_ID = 'sub-001';
const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const WATERMARK = new Date('2024-06-01T00:00:00Z');

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
 */
function createMockDb({
  subscription,
  lockResult,
}: {
  subscription?: { userProfileId: string } | undefined;
  lockResult?: {
    liveCatchUpState: string;
    newestLastModifiedDateTime: Date | null;
  };
}) {
  const txExecuteFn = vi.fn().mockResolvedValue(undefined);
  const txSelect = {
    from: vi.fn().mockReturnValue({
      where: vi.fn().mockReturnValue({
        for: vi.fn().mockReturnValue({
          then: vi.fn().mockImplementation((cb: (rows: any[]) => any) =>
            Promise.resolve(cb(lockResult ? [lockResult] : [])),
          ),
        }),
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
  const mockTx = {
    select: vi.fn().mockReturnValue(txSelect),
    update: vi.fn().mockReturnValue(txUpdate),
  };

  const dbExecuteFn = vi.fn().mockResolvedValue(undefined);
  const db = {
    query: {
      subscriptions: {
        findFirst: vi.fn().mockResolvedValue(subscription),
      },
    },
    transaction: vi.fn(async (cb: (tx: any) => Promise<any>) => cb(mockTx)),
    update: vi.fn().mockReturnValue({
      set: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          execute: dbExecuteFn,
        }),
      }),
    }),
    __mockTx: mockTx,
    __dbExecuteFn: dbExecuteFn,
  };

  return db;
}

function createCommand({
  graphApi,
  amqp,
  db,
}: {
  graphApi: ReturnType<typeof createMockGraphApi>;
  amqp: ReturnType<typeof createMockAmqp>;
  db: ReturnType<typeof createMockDb>;
}): LiveCatchUpCommand {
  return new LiveCatchUpCommand(
    createMockGraphClientFactory(graphApi) as any,
    amqp as any,
    db as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LiveCatchUpCommand', () => {
  let graphApi: ReturnType<typeof createMockGraphApi>;
  let amqp: ReturnType<typeof createMockAmqp>;

  beforeEach(() => {
    graphApi = createMockGraphApi();
    amqp = createMockAmqp();
    vi.clearAllMocks();
  });

  it('skips when subscription is not found', async () => {
    const db = createMockDb({ subscription: undefined, lockResult: undefined });
    const command = createCommand({ graphApi, amqp, db });

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
      },
    });
    const command = createCommand({ graphApi, amqp, db });

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
      },
    });
    const command = createCommand({ graphApi, amqp, db });

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
    const command = createCommand({ graphApi, amqp, db });

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
      },
    });
    const command = createCommand({ graphApi, amqp, db });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // Both emails published with high priority
    expect(amqp.publish).toHaveBeenCalledTimes(2);
    for (const call of amqp.publish.mock.calls) {
      expect(call[3]).toEqual(expect.objectContaining({ priority: 2 }));
    }

    // State set to 'ready' via db.update (outside transaction)
    const lastUpdateSetCall = db.update.mock.results[db.update.mock.calls.length - 1].value.set;
    expect(lastUpdateSetCall).toHaveBeenCalledWith(
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
      },
    });
    const command = createCommand({ graphApi, amqp, db });

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
      },
    });
    const command = createCommand({ graphApi, amqp, db });

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
      },
    });
    const command = createCommand({ graphApi, amqp, db });

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
    const emails = [
      makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z'),
    ];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb({
      subscription: { userProfileId: USER_PROFILE_ID },
      lockResult: {
        liveCatchUpState: 'ready',
        newestLastModifiedDateTime: WATERMARK,
      },
    });
    const command = createCommand({ graphApi, amqp, db });

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
      },
    });
    const command = createCommand({ graphApi, amqp, db });

    // Should NOT throw
    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    // State set to 'failed'
    const lastUpdateSetCall = db.update.mock.results[db.update.mock.calls.length - 1].value.set;
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
      },
    });
    const command = createCommand({ graphApi, amqp, db });

    await command.run({ subscriptionId: SUBSCRIPTION_ID, messageIds: [] });

    expect(graphApi.filter).toHaveBeenCalledWith(
      `lastModifiedDateTime ge ${WATERMARK.toISOString()}`,
    );
  });
});
