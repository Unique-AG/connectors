/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { GraphError } from '@microsoft/microsoft-graph-client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DiscoverDelegatedAccessCommand } from './discover-delegated-access.command';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DELEGATE_USER_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef1';
const OWNER_USER_ID_1 = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const OWNER_USER_ID_2 = 'user_profile_01jxk5r1s2fq9att23mp4z5ef3';
const OWNER_EMAIL_1 = 'owner1@example.com';
const OWNER_EMAIL_2 = 'owner2@example.com';

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

function createMockDb({
  connectedUsers = [] as Array<{ userProfileId: string; email: string | null }>,
} = {}) {
  const insertOnConflictDoUpdate = vi.fn().mockResolvedValue(undefined);
  const insertValues = vi.fn().mockReturnValue({ onConflictDoUpdate: insertOnConflictDoUpdate });
  const insert = vi.fn().mockReturnValue({ values: insertValues });

  const deleteWhere = vi.fn().mockResolvedValue(undefined);
  const deleteFn = vi.fn().mockReturnValue({ where: deleteWhere });

  const selectGroupBy = vi.fn().mockResolvedValue(connectedUsers);
  const selectWhere = vi.fn().mockReturnValue({ groupBy: selectGroupBy });
  const select = vi.fn().mockReturnValue({
    from: vi.fn().mockReturnValue({
      innerJoin: vi.fn().mockReturnValue({
        where: selectWhere,
      }),
    }),
  });

  return {
    select,
    insert,
    delete: deleteFn,
    __insertOnConflictDoUpdate: insertOnConflictDoUpdate,
    __insertValues: insertValues,
    __insert: insert,
    __deleteWhere: deleteWhere,
    __delete: deleteFn,
    __selectWhere: selectWhere,
    __selectGroupBy: selectGroupBy,
  };
}

function createCommand({
  graphApi = createMockGraphApi(),
  db = createMockDb(),
}: {
  graphApi?: ReturnType<typeof createMockGraphApi>;
  db?: ReturnType<typeof createMockDb>;
} = {}): DiscoverDelegatedAccessCommand {
  return new DiscoverDelegatedAccessCommand(
    createMockGraphClientFactory(graphApi) as any,
    db as any,
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

  it('upserts row when owner has mail folders', async () => {
    graphApi.get.mockResolvedValue({ value: [{ id: 'folder-1' }] });

    const db = createMockDb({
      connectedUsers: [{ userProfileId: OWNER_USER_ID_1, email: OWNER_EMAIL_1 }],
    });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    expect(db.__insert).toHaveBeenCalledOnce();
    expect(db.__insertValues).toHaveBeenCalledWith(
      expect.objectContaining({
        delegateUserId: DELEGATE_USER_ID,
        ownerUserId: OWNER_USER_ID_1,
        lastDiscoveredAt: expect.any(Date),
      }),
    );
    expect(db.__insertOnConflictDoUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        set: expect.objectContaining({ lastDiscoveredAt: expect.any(Date) }),
      }),
    );
    expect(db.__deleteWhere).not.toHaveBeenCalled();
  });

  it('does not upsert when a non-GraphError is thrown', async () => {
    graphApi.get.mockRejectedValue(new Error('Network failure'));

    const db = createMockDb({
      connectedUsers: [{ userProfileId: OWNER_USER_ID_1, email: OWNER_EMAIL_1 }],
    });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__deleteWhere).not.toHaveBeenCalled();
  });

  it('deletes pipeline row on 403 response', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(403));

    const db = createMockDb({
      connectedUsers: [{ userProfileId: OWNER_USER_ID_1, email: OWNER_EMAIL_1 }],
    });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    expect(db.__delete).toHaveBeenCalledOnce();
    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('deletes pipeline row on 404 response', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(404));

    const db = createMockDb({
      connectedUsers: [{ userProfileId: OWNER_USER_ID_1, email: OWNER_EMAIL_1 }],
    });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    expect(db.__delete).toHaveBeenCalledOnce();
    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('leaves row untouched on 429 rate limit', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(429));

    const db = createMockDb({
      connectedUsers: [{ userProfileId: OWNER_USER_ID_1, email: OWNER_EMAIL_1 }],
    });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('leaves row untouched on 500 transient error', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(500));

    const db = createMockDb({
      connectedUsers: [{ userProfileId: OWNER_USER_ID_1, email: OWNER_EMAIL_1 }],
    });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('leaves row untouched on 503 transient error', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(503));

    const db = createMockDb({
      connectedUsers: [{ userProfileId: OWNER_USER_ID_1, email: OWNER_EMAIL_1 }],
    });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('skips owner with null email', async () => {
    const db = createMockDb({
      connectedUsers: [{ userProfileId: OWNER_USER_ID_1, email: null }],
    });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    expect(graphApi.get).not.toHaveBeenCalled();
    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('processes owners in batches of 100 — 150 owners produce 2 batches', async () => {
    graphApi.get.mockResolvedValue({ value: [{ id: 'folder-1' }] });

    const owners = Array.from({ length: 150 }, (_, i) => ({
      userProfileId: `user_profile_${String(i).padStart(26, '0')}`,
      email: `owner${i}@example.com`,
    }));

    const db = createMockDb({ connectedUsers: owners });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    // Each of 150 owners gets a mailFolders call
    expect(graphApi.get).toHaveBeenCalledTimes(150);
    // Each succeeded → 150 upserts
    expect(db.__insert).toHaveBeenCalledTimes(150);
  });

  it('processes all owners across batches — first batch 100, second batch 50', async () => {
    graphApi.get.mockResolvedValue({ value: [{ id: 'folder-1' }] });

    const firstBatch = Array.from({ length: 100 }, (_, i) => ({
      userProfileId: `user_profile_a${String(i).padStart(25, '0')}`,
      email: `a${i}@example.com`,
    }));
    const secondBatch = Array.from({ length: 50 }, (_, i) => ({
      userProfileId: `user_profile_b${String(i).padStart(25, '0')}`,
      email: `b${i}@example.com`,
    }));

    const db = createMockDb({ connectedUsers: [...firstBatch, ...secondBatch] });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    expect(graphApi.get).toHaveBeenCalledTimes(150);
  });

  it('processes both owners independently — one upserts, one deletes on 403', async () => {
    graphApi.get
      .mockResolvedValueOnce({ value: [{ id: 'folder-1' }] }) // OWNER_USER_ID_1 succeeds
      .mockRejectedValueOnce(makeGraphError(403)); // OWNER_USER_ID_2 is 403

    const db = createMockDb({
      connectedUsers: [
        { userProfileId: OWNER_USER_ID_1, email: OWNER_EMAIL_1 },
        { userProfileId: OWNER_USER_ID_2, email: OWNER_EMAIL_2 },
      ],
    });
    const command = createCommand({ graphApi, db });

    await command.run({ delegateUserId: DELEGATE_USER_ID });

    expect(db.__insert).toHaveBeenCalledOnce();
    expect(db.__delete).toHaveBeenCalledOnce();
  });
});
