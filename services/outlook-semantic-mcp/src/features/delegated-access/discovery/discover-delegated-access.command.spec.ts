/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { GraphError } from '@microsoft/microsoft-graph-client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DiscoverDelegatedAccessCommand } from './discover-delegated-access.command';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const USER_ID_A = 'user_profile_01jxk5r1s2fq9att23mp4z5ef1';
const USER_ID_B = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const USER_ID_C = 'user_profile_01jxk5r1s2fq9att23mp4z5ef3';
const EMAIL_A = 'user-a@example.com';
const EMAIL_B = 'user-b@example.com';
const EMAIL_C = 'user-c@example.com';

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
  return {
    createClientForUser: vi.fn().mockReturnValue({
      api: vi.fn().mockReturnValue(graphApi),
    }),
  };
}

function createMockDb() {
  const insertOnConflictDoUpdate = vi.fn().mockResolvedValue(undefined);
  const insertValues = vi.fn().mockReturnValue({ onConflictDoUpdate: insertOnConflictDoUpdate });
  const insert = vi.fn().mockReturnValue({ values: insertValues });

  const deleteWhere = vi.fn().mockResolvedValue(undefined);
  const deleteFn = vi.fn().mockReturnValue({ where: deleteWhere });

  return {
    insert,
    delete: deleteFn,
    __insertOnConflictDoUpdate: insertOnConflictDoUpdate,
    __insertValues: insertValues,
    __insert: insert,
    __deleteWhere: deleteWhere,
    __delete: deleteFn,
  };
}

function createMockPersistentCacheService() {
  return {
    setWith: vi.fn().mockResolvedValue(undefined),
  };
}

function createCommand({
  graphApi = createMockGraphApi(),
  db = createMockDb(),
  persistentCacheService = createMockPersistentCacheService(),
}: {
  graphApi?: ReturnType<typeof createMockGraphApi>;
  db?: ReturnType<typeof createMockDb>;
  persistentCacheService?: ReturnType<typeof createMockPersistentCacheService>;
} = {}): DiscoverDelegatedAccessCommand {
  const command = new DiscoverDelegatedAccessCommand(
    createMockGraphClientFactory(graphApi) as any,
    db as any,
    persistentCacheService as any,
  );
  // Stub decide() so unit tests bypass cache logic and test graph/db behavior directly
  vi.spyOn(command, 'decide').mockResolvedValue({
    action: 'proceed',
    lastProcessedDelegateId: null,
    lastProcessedOwnerIdForDelegate: null,
  });
  return command;
}

/**
 * Mocks fetchBatch so all users arrive in a single delegates batch and each
 * delegate's owners arrive in a single owners batch. Avoids the need to mock
 * the Drizzle query chain inside fetchBatch.
 */
function mockFetchBatchForUsers(
  command: DiscoverDelegatedAccessCommand,
  users: Array<{ userProfileId: string; email: string | null }>,
) {
  const spy = vi.spyOn(command as any, 'fetchBatch');
  spy.mockResolvedValueOnce(users);
  for (const { userProfileId } of users) {
    spy.mockResolvedValueOnce(users.filter((u) => u.userProfileId !== userProfileId));
    spy.mockResolvedValueOnce([]);
  }
  spy.mockResolvedValueOnce([]);
  return spy;
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

    await command.run();

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

    await command.run();

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

    await command.run();

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

    await command.run();

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('deletes pipeline rows on 403 response', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(403));
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run();

    expect(db.__delete).toHaveBeenCalledTimes(2);
    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('deletes pipeline rows on 404 response', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(404));
    const db = createMockDb();
    const command = createCommand({ graphApi, db });
    mockFetchBatchForUsers(command, [
      { userProfileId: USER_ID_A, email: EMAIL_A },
      { userProfileId: USER_ID_B, email: EMAIL_B },
    ]);

    await command.run();

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

    await command.run();

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

    await command.run();

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

    await command.run();

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

    await command.run();

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

    await command.run();

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

    await command.run();

    expect(db.__insert).toHaveBeenCalledTimes(2); // A→B and C→B
    expect(spy).toHaveBeenCalledWith({ lastFetchedId: USER_ID_A });
    expect(spy).toHaveBeenCalledWith({ lastFetchedId: USER_ID_C });
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

    await command.run();

    expect(db.__insert).toHaveBeenCalledTimes(2); // A→B and A→C
    expect(spy).toHaveBeenCalledWith({ lastFetchedId: USER_ID_B, excludedProfileIds: [USER_ID_A] });
    expect(spy).toHaveBeenCalledWith({ lastFetchedId: USER_ID_C, excludedProfileIds: [USER_ID_A] });
  });

  it('excludes the delegate from its own owner query', async () => {
    const db = createMockDb();
    const command = createCommand({ graphApi, db });

    const spy = vi.spyOn(command as any, 'fetchBatch');
    spy.mockResolvedValueOnce([{ userProfileId: USER_ID_A, email: EMAIL_A }]); // delegates
    spy.mockResolvedValueOnce([]); // A's owners (empty)
    spy.mockResolvedValueOnce([]); // no more delegates

    await command.run();

    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ excludedProfileIds: [USER_ID_A] }));
  });
});
