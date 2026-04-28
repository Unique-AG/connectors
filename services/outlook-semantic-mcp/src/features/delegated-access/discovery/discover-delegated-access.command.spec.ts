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

  it('upserts rows for all user pairs when access is granted', async () => {
    graphApi.get.mockResolvedValue({ value: [{ id: 'folder-1' }] });

    const db = createMockDb({
      connectedUsers: [
        { userProfileId: USER_ID_A, email: EMAIL_A },
        { userProfileId: USER_ID_B, email: EMAIL_B },
      ],
    });
    const command = createCommand({ graphApi, db });

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
    expect(db.__deleteWhere).not.toHaveBeenCalled();
  });

  it('does not upsert when a non-GraphError is thrown', async () => {
    graphApi.get.mockRejectedValue(new Error('Network failure'));

    const db = createMockDb({
      connectedUsers: [
        { userProfileId: USER_ID_A, email: EMAIL_A },
        { userProfileId: USER_ID_B, email: EMAIL_B },
      ],
    });
    const command = createCommand({ graphApi, db });

    await command.run();

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__deleteWhere).not.toHaveBeenCalled();
  });

  it('deletes pipeline rows on 403 response', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(403));

    const db = createMockDb({
      connectedUsers: [
        { userProfileId: USER_ID_A, email: EMAIL_A },
        { userProfileId: USER_ID_B, email: EMAIL_B },
      ],
    });
    const command = createCommand({ graphApi, db });

    await command.run();

    expect(db.__delete).toHaveBeenCalledTimes(2);
    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('deletes pipeline rows on 404 response', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(404));

    const db = createMockDb({
      connectedUsers: [
        { userProfileId: USER_ID_A, email: EMAIL_A },
        { userProfileId: USER_ID_B, email: EMAIL_B },
      ],
    });
    const command = createCommand({ graphApi, db });

    await command.run();

    expect(db.__delete).toHaveBeenCalledTimes(2);
    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('leaves rows untouched on 429 rate limit', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(429));

    const db = createMockDb({
      connectedUsers: [
        { userProfileId: USER_ID_A, email: EMAIL_A },
        { userProfileId: USER_ID_B, email: EMAIL_B },
      ],
    });
    const command = createCommand({ graphApi, db });

    await command.run();

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('leaves rows untouched on 500 transient error', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(500));

    const db = createMockDb({
      connectedUsers: [
        { userProfileId: USER_ID_A, email: EMAIL_A },
        { userProfileId: USER_ID_B, email: EMAIL_B },
      ],
    });
    const command = createCommand({ graphApi, db });

    await command.run();

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('leaves rows untouched on 503 transient error', async () => {
    graphApi.get.mockRejectedValue(makeGraphError(503));

    const db = createMockDb({
      connectedUsers: [
        { userProfileId: USER_ID_A, email: EMAIL_A },
        { userProfileId: USER_ID_B, email: EMAIL_B },
      ],
    });
    const command = createCommand({ graphApi, db });

    await command.run();

    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('skips all pairs when all owners have null email', async () => {
    const db = createMockDb({
      connectedUsers: [
        { userProfileId: USER_ID_A, email: null },
        { userProfileId: USER_ID_B, email: null },
      ],
    });
    const command = createCommand({ graphApi, db });

    await command.run();

    expect(graphApi.get).not.toHaveBeenCalled();
    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });

  it('processes users independently — one upserts, one deletes on 403', async () => {
    graphApi.get
      .mockResolvedValueOnce({ value: [{ id: 'folder-1' }] }) // A→B succeeds
      .mockRejectedValueOnce(makeGraphError(403)); // B→A fails

    const db = createMockDb({
      connectedUsers: [
        { userProfileId: USER_ID_A, email: EMAIL_A },
        { userProfileId: USER_ID_B, email: EMAIL_B },
      ],
    });
    const command = createCommand({ graphApi, db });

    await command.run();

    expect(db.__insert).toHaveBeenCalledOnce();
    expect(db.__delete).toHaveBeenCalledOnce();
  });

  it('processes all user pairs across all connected users', async () => {
    graphApi.get.mockResolvedValue({ value: [{ id: 'folder-1' }] });

    const db = createMockDb({
      connectedUsers: [
        { userProfileId: USER_ID_A, email: EMAIL_A },
        { userProfileId: USER_ID_B, email: EMAIL_B },
        { userProfileId: USER_ID_C, email: EMAIL_C },
      ],
    });
    const command = createCommand({ graphApi, db });

    await command.run();

    // 3 users → 3*2 = 6 directed pairs → 6 graph calls, 6 upserts
    expect(graphApi.get).toHaveBeenCalledTimes(6);
    expect(db.__insert).toHaveBeenCalledTimes(6);
  });

  it('does nothing when no connected users exist', async () => {
    const db = createMockDb({ connectedUsers: [] });
    const command = createCommand({ graphApi, db });

    await command.run();

    expect(graphApi.get).not.toHaveBeenCalled();
    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
  });
});
