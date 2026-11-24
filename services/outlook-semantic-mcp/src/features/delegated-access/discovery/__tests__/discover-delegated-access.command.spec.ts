/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { UpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { GraphError } from '@microsoft/microsoft-graph-client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DiscoverDelegatedAccessCommand } from '../discover-delegated-access.command';

vi.mock('../../../../utils/sleep', () => ({ sleep: vi.fn().mockResolvedValue(undefined) }));

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const USER_ID_A = 'user_profile_01jxk5r1s2fq9att23mp4z5ef1';
const USER_ID_B = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const USER_ID_C = 'user_profile_01jxk5r1s2fq9att23mp4z5ef3';
const EMAIL_A = 'user-a@example.com';
const EMAIL_B = 'user-b@example.com';
const EMAIL_C = 'user-c@example.com';
const CYCLE_STARTED_AT = new Date('2026-11-24T00:00:00.000Z');
const RUN_ID = 'run-under-test';

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function makeGraphError(statusCode: number): GraphError {
  const err = new GraphError(statusCode, 'Graph error');
  err.statusCode = statusCode;
  return err;
}

function createMockGraphApi() {
  return {
    top: vi.fn().mockReturnThis(),
    select: vi.fn().mockReturnThis(),
    get: vi.fn(),
  };
}

function createMockGraphClientFactory(graphApi: ReturnType<typeof createMockGraphApi>) {
  const api = vi.fn().mockReturnValue(graphApi);
  return {
    createClientForUser: vi.fn().mockReturnValue({ api }),
    __api: api,
  };
}

function createMockDb() {
  const insertOnConflictDoUpdate = vi.fn().mockResolvedValue(undefined);
  const insertValues = vi.fn().mockReturnValue({ onConflictDoUpdate: insertOnConflictDoUpdate });
  const insert = vi.fn().mockReturnValue({ values: insertValues });

  const deleteWhere = vi.fn().mockResolvedValue(undefined);
  const deleteFn = vi.fn().mockReturnValue({ where: deleteWhere });

  const updateWhere = vi.fn().mockResolvedValue(undefined);
  const updateSet = vi.fn().mockReturnValue({ where: updateWhere });
  const update = vi.fn().mockReturnValue({ set: updateSet });

  const selectGroupBy = vi.fn().mockResolvedValue([]);
  const select = vi.fn().mockReturnValue({
    from: vi.fn().mockReturnValue({
      innerJoin: vi.fn().mockReturnValue({
        innerJoin: vi.fn().mockReturnValue({ groupBy: selectGroupBy }),
      }),
    }),
  });

  return {
    insert,
    delete: deleteFn,
    update,
    select,
    __updateSet: updateSet,
    __updateWhere: updateWhere,
    __selectGroupBy: selectGroupBy,
    __insertOnConflictDoUpdate: insertOnConflictDoUpdate,
    __insertValues: insertValues,
    __insert: insert,
    __deleteWhere: deleteWhere,
    __delete: deleteFn,
  };
}

function createMockPersistentCacheService() {
  return {
    get: vi.fn().mockResolvedValue(null),
    setWith: vi.fn().mockResolvedValue(undefined),
  };
}

function createCommand({
  graphApi = createMockGraphApi(),
  db = createMockDb(),
  persistentCacheService = createMockPersistentCacheService(),
  graphClientFactory,
  stubDecide = true,
}: {
  graphApi?: ReturnType<typeof createMockGraphApi>;
  db?: ReturnType<typeof createMockDb>;
  persistentCacheService?: ReturnType<typeof createMockPersistentCacheService>;
  graphClientFactory?: ReturnType<typeof createMockGraphClientFactory>;
  stubDecide?: boolean;
} = {}): DiscoverDelegatedAccessCommand {
  const command = new DiscoverDelegatedAccessCommand(
    (graphClientFactory ?? createMockGraphClientFactory(graphApi)) as any,
    {} as any,
    {} as any,
    db as any,
    persistentCacheService as any,
    {
      measureDiscoverRun: (fn: () => Promise<unknown>) => fn(),
      measureDiscoverUser: (fn: () => Promise<unknown>) => fn(),
    } as any,
  );
  if (stubDecide) {
    // Bypass the cache logic so these tests exercise the graph/db behavior directly
    vi.spyOn(command, 'decide').mockResolvedValue({
      action: 'proceed',
      cycleStartedAt: CYCLE_STARTED_AT,
      runId: RUN_ID,
    });
  }
  return command;
}

/**
 * Mocks fetchBatch so all users arrive in a single delegates batch and each
 * delegate's owners arrive in a single owners batch. Avoids the need to mock
 * the Drizzle query chain inside fetchBatch.
 */
function mockFetchBatchForUsers(
  command: DiscoverDelegatedAccessCommand,
  users: Array<{ userProfileId: string; email: string | null; source?: string }>,
) {
  // Answers by the call's arguments, so a delegate that stops early does not shift the batches.
  return vi
    .spyOn(command as any, 'fetchBatch')
    .mockImplementation(async (args: any) =>
      args.lastFetchedId
        ? []
        : users.filter((user) => !args.excludedProfileIds?.includes(user.userProfileId)),
    );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DiscoverDelegatedAccessCommand', () => {
  let graphApi: ReturnType<typeof createMockGraphApi>;

  beforeEach(() => {
    graphApi = createMockGraphApi();
    vi.clearAllMocks();
  });

  it('does nothing when no users exist', async () => {
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    vi.spyOn(command as any, 'fetchBatch').mockResolvedValue([]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(graphApi.get).not.toHaveBeenCalled();
    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('upserts rows for all user pairs when access is granted', async () => {
    graphApi.get.mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    // A→B and B→A: 2 pairs → 2 upserts
    expect(db.__insert).toHaveBeenCalledTimes(2);
    expect(db.__insertValues).toHaveBeenCalledWith(
      expect.objectContaining({ lastDiscoveredAt: expect.any(Date) }),
    );
    expect(db.__insertOnConflictDoUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        set: expect.objectContaining({ lastDiscoveredAt: expect.any(Date) }),
      }),
    );
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('processes all directed pairs across three users', async () => {
    graphApi.get.mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
      { userProfileId: USER_ID_C, email: EMAIL_C },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    // 3 users → 6 directed pairs → 6 graph calls, 6 upserts
    expect(graphApi.get).toHaveBeenCalledTimes(6);
    expect(db.__insert).toHaveBeenCalledTimes(6);
  });

  it('does not upsert or delete when a non-GraphError is thrown', async () => {
    graphApi.get.mockRejectedValue(new Error('Network failure'));
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('deletes accounts rows on 403 response', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(403));
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__delete).toHaveBeenCalledTimes(2);
    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('deletes accounts rows on 404 response', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(404));
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__delete).toHaveBeenCalledTimes(2);
    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('leaves rows untouched on 429 rate limit', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(429));
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('leaves rows untouched on 500 transient error', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(500));
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('leaves rows untouched on 503 transient error', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(503));
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('processes users independently — one upserts, one deletes on 403', async () => {
    graphApi.get
      .mockResolvedValueOnce(undefined) // A→B succeeds
      .mockRejectedValueOnce(makeGraphError(403)); // B→A fails

    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__insert).toHaveBeenCalledOnce();
    expect(db.__delete).toHaveBeenCalledOnce();
  });

  it('skips owner with null email without making a graph call', async () => {
    graphApi.get.mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    // A has email, B has null — A→B skipped, B→A proceeds
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: null },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(graphApi.get).toHaveBeenCalledTimes(1);
    expect(db.__insert).toHaveBeenCalledTimes(1);
  });

  // --- Pagination ---

  it('paginates through multiple delegate batches using cursor', async () => {
    graphApi.get.mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });

    const spy = vi.spyOn(command as any, 'fetchBatch');
    spy.mockResolvedValueOnce([{ userProfileId: USER_ID_A, email: EMAIL_A }]); // first delegates batch
    spy.mockResolvedValueOnce([{ userProfileId: USER_ID_B, email: EMAIL_B }]); // A's owners
    spy.mockResolvedValueOnce([]); // no more A's owners
    spy.mockResolvedValueOnce([{ userProfileId: USER_ID_C, email: EMAIL_C }]); // second delegates batch
    spy.mockResolvedValueOnce([{ userProfileId: USER_ID_B, email: EMAIL_B }]); // C's owners
    spy.mockResolvedValueOnce([]); // no more C's owners
    spy.mockResolvedValueOnce([]); // no more delegates

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__insert).toHaveBeenCalledTimes(2); // A→B and C→B
    expect(spy).toHaveBeenCalledWith({
      lastFetchedId: USER_ID_A,
      includeSharedMailboxes: false,
      pendingDiscoveryBefore: CYCLE_STARTED_AT,
    });
    expect(spy).toHaveBeenCalledWith({
      lastFetchedId: USER_ID_C,
      includeSharedMailboxes: false,
      pendingDiscoveryBefore: CYCLE_STARTED_AT,
    });
  });

  it('paginates through multiple owner batches for a single delegate', async () => {
    graphApi.get.mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });

    const spy = vi.spyOn(command as any, 'fetchBatch');
    spy.mockResolvedValueOnce([{ userProfileId: USER_ID_A, email: EMAIL_A }]); // delegates
    spy.mockResolvedValueOnce([{ userProfileId: USER_ID_B, email: EMAIL_B }]); // A's owners first batch
    spy.mockResolvedValueOnce([{ userProfileId: USER_ID_C, email: EMAIL_C }]); // A's owners second batch
    spy.mockResolvedValueOnce([]); // no more A's owners
    spy.mockResolvedValueOnce([]); // no more delegates

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__insert).toHaveBeenCalledTimes(2); // A→B and A→C
    expect(spy).toHaveBeenCalledWith({
      lastFetchedId: USER_ID_B,
      excludedProfileIds: [USER_ID_A],
      includeSharedMailboxes: true,
    });
    expect(spy).toHaveBeenCalledWith({
      lastFetchedId: USER_ID_C,
      excludedProfileIds: [USER_ID_A],
      includeSharedMailboxes: true,
    });
  });

  it('excludes the delegate from its own owner query', async () => {
    const db = createMockDb();
    const command = createCommand({ graphApi, db });

    const spy = vi.spyOn(command as any, 'fetchBatch');
    spy.mockResolvedValueOnce([{ userProfileId: USER_ID_A, email: EMAIL_A }]); // delegates
    spy.mockResolvedValueOnce([]); // A's owners (empty)
    spy.mockResolvedValueOnce([]); // no more delegates

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ excludedProfileIds: [USER_ID_A] }));
  });

  it('probes a dual owner via /messages and records full delegated access', async () => {
    graphApi.get.mockResolvedValue(undefined);
    const graphClientFactory = createMockGraphClientFactory(graphApi);
    const db = createMockDb();
    const command = createCommand({ graphApi, db, graphClientFactory });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A, source: 'oauth' },
      {
        userProfileId: USER_ID_B,
        email: EMAIL_B,
        source: 'shared-mailbox-with-login',
      },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(graphClientFactory.__api).toHaveBeenCalledWith(`/users/${EMAIL_B}/messages`);
    expect(db.__insertValues).toHaveBeenCalledWith(
      expect.objectContaining({ hasFullDelegatedAccess: true }),
    );
  });

  it('uses a dual profile as a delegate for another owner', async () => {
    graphApi.get.mockResolvedValue(undefined);
    const graphClientFactory = createMockGraphClientFactory(graphApi);
    const db = createMockDb();
    const command = createCommand({ graphApi, db, graphClientFactory });
    mockFetchBatchForUsers(command, [
      {
        userProfileId: USER_ID_A,
        email: EMAIL_A,
        source: 'shared-mailbox-with-login',
      },
      { userProfileId: USER_ID_B, email: EMAIL_B, source: 'oauth' },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(graphClientFactory.createClientForUser).toHaveBeenCalledWith(USER_ID_A);
    expect(graphClientFactory.__api).toHaveBeenCalledWith(`/users/${EMAIL_B}/mailFolders`);
  });

  // --- Per-delegate outcome ---

  it('marks a delegate discovered once every owner has been checked', async () => {
    graphApi.get.mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__updateSet).toHaveBeenCalledTimes(2);
    expect(db.__updateSet).toHaveBeenCalledWith({ delegatedAccessDiscoveredAt: expect.any(Date) });
  });

  it("keeps a delegate's records and moves on to the next delegate after a 401", async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(401)) // A→B: A's token cannot be used
      .mockResolvedValueOnce(undefined); // B→A succeeds
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__delete).not.toHaveBeenCalled();
    expect(db.__insert).toHaveBeenCalledOnce();
    expect(db.__updateSet).toHaveBeenCalledOnce();
  });

  it('keeps going after a delegate exhausts its rate limit retries', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(429))
      .mockRejectedValueOnce(makeGraphError(429))
      .mockRejectedValueOnce(makeGraphError(429))
      .mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__insert).toHaveBeenCalledOnce(); // B→A
    expect(db.__updateSet).toHaveBeenCalledOnce();
  });

  it("clears a delegate's records when its Microsoft grant is permanently invalid", async () => {
    graphApi.get.mockRejectedValueOnce(new UpstreamCredentialRevokedError('invalid_grant'));
    graphApi.get.mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__delete).toHaveBeenCalledOnce();
    expect(db.__updateSet).toHaveBeenCalledOnce(); // only B is marked discovered
  });

  it("clears a delegate's records when the Graph SDK hands back the revoked grant as a GraphError", async () => {
    // The SDK rethrows a middleware's error as its own GraphError, keeping the name as `code`.
    const wrappedByGraphSdk = Object.assign(new GraphError(-1, 'Re-authentication required'), {
      code: 'UpstreamCredentialRevokedError',
    });
    graphApi.get.mockRejectedValueOnce(wrappedByGraphSdk);
    graphApi.get.mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__delete).toHaveBeenCalledOnce();
    expect(db.__updateSet).toHaveBeenCalledOnce(); // only B is marked discovered
  });

  it("clears a delegate's records when an ordinary 401 rejects before another owner check reports the revoked grant", async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(401)) // A→B
      .mockRejectedValueOnce(new UpstreamCredentialRevokedError('invalid_grant')) // A→C
      .mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
      { userProfileId: USER_ID_C, email: EMAIL_C },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__delete).toHaveBeenCalledOnce();
    expect(db.__updateSet).toHaveBeenCalledTimes(2); // only B and C are marked discovered
  });

  it("keeps a delegate's records when its owner checks only return ordinary 401s", async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(401)) // A→B
      .mockRejectedValueOnce(makeGraphError(401)) // A→C
      .mockResolvedValue(undefined);
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
      { userProfileId: USER_ID_C, email: EMAIL_C },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__delete).not.toHaveBeenCalled();
    expect(db.__updateSet).toHaveBeenCalledTimes(2); // A stays pending
  });

  it('ends the run ready when a delegate fails', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(401));
    const persistentCacheService = createMockPersistentCacheService();
    const command = createCommand({ graphApi, persistentCacheService });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    const update = vi.fn();
    const finalStateUpdate = persistentCacheService.setWith.mock.calls.at(-1)?.[1];
    await finalStateUpdate?.({
      currentValue: {
        dataType: 'DelegatedAccessDiscovery',
        payload: {
          state: 'running',
          runId: RUN_ID,
          cycleStartedAt: 1,
          lastProgressRegisteredAt: 1,
        },
      },
      update,
    });
    expect(update).toHaveBeenCalledWith(
      expect.objectContaining({ payload: expect.objectContaining({ state: 'ready' }) }),
    );
  });

  it('leaves the state alone when another run took over after this one went stale', async () => {
    graphApi.get.mockResolvedValue(undefined);
    const db = createMockDb();
    const persistentCacheService = createMockPersistentCacheService();
    const update = vi.fn();
    persistentCacheService.setWith.mockImplementation((_key, fn) =>
      fn({
        currentValue: {
          dataType: 'DelegatedAccessDiscovery',
          payload: {
            state: 'running',
            runId: 'newer-run',
            cycleStartedAt: 1,
            lastProgressRegisteredAt: 1,
          },
        },
        update,
      }),
    );
    const command = createCommand({ graphApi, db, persistentCacheService });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(update).not.toHaveBeenCalled();
  });

  it('keeps going with the next delegate when stamping one fails', async () => {
    graphApi.get.mockResolvedValue(undefined);
    const db = createMockDb();
    db.__updateWhere.mockRejectedValueOnce(new Error('connection reset'));
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__updateWhere).toHaveBeenCalledTimes(2); // A failed, B still stamped
    expect(db.__insert).toHaveBeenCalledTimes(2);
  });

  it('stamps the time the owner checks started, not when they finished', async () => {
    const checksStart = new Date('2026-11-24T12:00:00.000Z');
    vi.useFakeTimers({ now: checksStart, toFake: ['Date'] });
    try {
      graphApi.get.mockImplementation(async () => {
        vi.setSystemTime(new Date(checksStart.getTime() + 60_000));
        return undefined;
      });
      const db = createMockDb();
      const command = createCommand({ graphApi, db });
      mockFetchBatchForUsers(command, [
        { userProfileId: USER_ID_A, email: EMAIL_A },
        { userProfileId: USER_ID_B, email: EMAIL_B },
      ]);

      await command.run({ newCycleRequestedAt: Date.now() });

      expect(db.__updateSet).toHaveBeenNthCalledWith(1, {
        delegatedAccessDiscoveredAt: checksStart,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('leaves a delegate pending when one of its owner checks failed', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(500)) // A→B fails (only rate limits are retried)
      .mockResolvedValue(undefined); // B→A succeeds
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(db.__updateSet).toHaveBeenCalledOnce(); // only B is marked discovered
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('fetches only the delegates the cycle has not discovered yet', async () => {
    const command = createCommand({ graphApi });
    const spy = vi.spyOn(command as any, 'fetchBatch').mockResolvedValue([]);

    await command.run({ newCycleRequestedAt: Date.now() });

    expect(spy).toHaveBeenCalledWith({
      includeSharedMailboxes: false,
      pendingDiscoveryBefore: CYCLE_STARTED_AT,
    });
  });

  describe('hasPendingDelegates', () => {
    it('is true when a delegate is pending in the cycle', async () => {
      const command = createCommand({ graphApi });
      const spy = vi
        .spyOn(command as any, 'fetchBatch')
        .mockResolvedValue([{ userProfileId: USER_ID_A, email: EMAIL_A }]);

      await expect(command.hasPendingDelegates(CYCLE_STARTED_AT)).resolves.toBe(true);
      expect(spy).toHaveBeenCalledWith({
        includeSharedMailboxes: false,
        pendingDiscoveryBefore: CYCLE_STARTED_AT,
      });
    });

    it('is false when no delegate is pending', async () => {
      const command = createCommand({ graphApi });
      vi.spyOn(command as any, 'fetchBatch').mockResolvedValue([]);

      await expect(command.hasPendingDelegates(CYCLE_STARTED_AT)).resolves.toBe(false);
    });
  });

  describe('decide', () => {
    const now = new Date('2026-11-24T12:00:00.000Z');
    const previousCycle = new Date('2026-11-24T00:00:00.000Z').getTime();

    const decideWith = async (currentValue: unknown, request: { newCycleRequestedAt?: number }) => {
      const create = vi.fn();
      const update = vi.fn();
      const persistentCacheService = createMockPersistentCacheService();
      persistentCacheService.setWith.mockImplementation((_key, fn) =>
        fn({ currentValue, create, update }),
      );
      const command = createCommand({ persistentCacheService, stubDecide: false });
      const decision = await command.decide(request);
      return { decision, create, update };
    };

    const discoveryState = (payload: Record<string, unknown>) => ({
      dataType: 'DelegatedAccessDiscovery',
      payload,
    });

    beforeEach(() => {
      vi.useFakeTimers({ now, toFake: ['Date'] });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('starts the first cycle now', async () => {
      const { decision, create } = await decideWith(null, {});

      expect(decision).toEqual({
        action: 'proceed',
        cycleStartedAt: now,
        runId: expect.any(String),
      });
      expect(create).toHaveBeenCalledWith({
        dataType: 'DelegatedAccessDiscovery',
        payload: {
          state: 'running',
          runId: expect.any(String),
          cycleStartedAt: now.getTime(),
          lastProgressRegisteredAt: now.getTime(),
        },
      });
    });

    it('starts a new cycle now when asked to', async () => {
      const { decision } = await decideWith(
        discoveryState({
          state: 'ready',
          cycleStartedAt: previousCycle,
          lastProgressRegisteredAt: previousCycle,
        }),
        { newCycleRequestedAt: now.getTime() },
      );

      expect(decision).toEqual({
        action: 'proceed',
        cycleStartedAt: now,
        runId: expect.any(String),
      });
    });

    it('continues the current cycle otherwise', async () => {
      const { decision, update } = await decideWith(
        discoveryState({
          state: 'ready',
          cycleStartedAt: previousCycle,
          lastProgressRegisteredAt: previousCycle,
        }),
        {},
      );

      expect(decision).toEqual({
        action: 'proceed',
        cycleStartedAt: new Date(previousCycle),
        runId: expect.any(String),
      });
      expect(update).toHaveBeenCalledWith({
        dataType: 'DelegatedAccessDiscovery',
        payload: {
          state: 'running',
          runId: expect.any(String),
          cycleStartedAt: previousCycle,
          lastProgressRegisteredAt: now.getTime(),
        },
      });
    });

    it('skips while another run is making progress', async () => {
      const { decision, update } = await decideWith(
        discoveryState({
          state: 'running',
          cycleStartedAt: previousCycle,
          lastProgressRegisteredAt: now.getTime() - 60_000,
        }),
        {},
      );

      expect(decision).toEqual(expect.objectContaining({ action: 'skip' }));
      expect(update).not.toHaveBeenCalled();
    });

    it('keeps a new cycle asked for while another run is making progress', async () => {
      const runInProgress = {
        state: 'running',
        cycleStartedAt: previousCycle,
        lastProgressRegisteredAt: now.getTime() - 60_000,
      };
      const { decision, update } = await decideWith(discoveryState(runInProgress), {
        newCycleRequestedAt: now.getTime(),
      });

      expect(decision).toEqual(expect.objectContaining({ action: 'skip' }));
      expect(update).toHaveBeenCalledWith({
        dataType: 'DelegatedAccessDiscovery',
        payload: { ...runInProgress, cycleStartedAt: now.getTime() },
      });
    });

    it('continues the cycle for a request redelivered after the run it started was killed', async () => {
      const killedRun = {
        state: 'running',
        cycleStartedAt: previousCycle,
        lastProgressRegisteredAt: now.getTime() - 10 * 60_000,
      };
      const { decision, update } = await decideWith(discoveryState(killedRun), {
        newCycleRequestedAt: previousCycle - 1_000,
      });

      expect(decision).toEqual({
        action: 'proceed',
        cycleStartedAt: new Date(previousCycle),
        runId: expect.any(String),
      });
      expect(update).toHaveBeenCalledWith({
        dataType: 'DelegatedAccessDiscovery',
        payload: {
          state: 'running',
          runId: expect.any(String),
          cycleStartedAt: previousCycle,
          lastProgressRegisteredAt: now.getTime(),
        },
      });
    });

    it('leaves the cycle alone for a redelivered request while its run is making progress', async () => {
      const { decision, update } = await decideWith(
        discoveryState({
          state: 'running',
          cycleStartedAt: previousCycle,
          lastProgressRegisteredAt: now.getTime() - 60_000,
        }),
        { newCycleRequestedAt: previousCycle - 1_000 },
      );

      expect(decision).toEqual(expect.objectContaining({ action: 'skip' }));
      expect(update).not.toHaveBeenCalled();
    });

    it('takes over a run that stopped making progress', async () => {
      const { decision } = await decideWith(
        discoveryState({
          state: 'running',
          cycleStartedAt: previousCycle,
          lastProgressRegisteredAt: now.getTime() - 10 * 60_000,
        }),
        {},
      );

      expect(decision).toEqual({
        action: 'proceed',
        cycleStartedAt: new Date(previousCycle),
        runId: expect.any(String),
      });
    });

    it('starts the cycle now for a state written before cycles were tracked', async () => {
      const { decision } = await decideWith(
        discoveryState({
          state: 'failed',
          lastProcessedDelegateId: USER_ID_A,
          lastProgressRegisteredAt: previousCycle,
        }),
        {},
      );

      expect(decision).toEqual({
        action: 'proceed',
        cycleStartedAt: now,
        runId: expect.any(String),
      });
    });
  });
});
