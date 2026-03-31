/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SyncDirectoriesForUserProfileCommand } from '../sync-directories-for-user-profile.command';

const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const USER_EMAIL = 'test@example.com';

function createMockDb() {
  return {
    execute: vi.fn().mockResolvedValue(undefined),
    select: vi.fn().mockReturnValue({
      from: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          execute: vi.fn().mockResolvedValue([{ count: 1 }]),
        }),
      }),
    }),
    update: vi.fn().mockReturnValue({
      set: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          execute: vi.fn().mockResolvedValue(undefined),
        }),
      }),
    }),
    delete: vi.fn().mockReturnValue({
      where: vi.fn().mockReturnValue({
        execute: vi.fn().mockResolvedValue(undefined),
      }),
    }),
    query: {
      directories: {
        findMany: vi.fn().mockResolvedValue([]),
      },
    },
  };
}

function createCommand() {
  const db = createMockDb();

  const getUserProfileQuery = {
    run: vi.fn().mockResolvedValue({
      id: USER_PROFILE_ID,
      email: USER_EMAIL,
      providerUserId: 'provider-user-1',
    }),
  };

  const fetchAllDirectoriesFromOutlookQuery = {
    run: vi.fn().mockResolvedValue([]),
  };

  const syncSystemDirectoriesCommand = {
    run: vi.fn().mockResolvedValue(undefined),
  };

  const createRootScopeCommand = {
    run: vi.fn().mockResolvedValue(undefined),
  };

  const upsertDirectoryCommand = {
    run: vi.fn().mockResolvedValue({ id: 'dir-001' }),
  };

  const uniqueApi = {
    scopes: { getByExternalId: vi.fn().mockResolvedValue(null) },
    files: {
      getIdsByScopeAndMetadataKey: vi.fn().mockResolvedValue([]),
      deleteByIds: vi.fn().mockResolvedValue(undefined),
    },
  };

  const command = new SyncDirectoriesForUserProfileCommand(
    db as any,
    uniqueApi as any,
    fetchAllDirectoriesFromOutlookQuery as any,
    getUserProfileQuery as any,
    syncSystemDirectoriesCommand as any,
    createRootScopeCommand as any,
    upsertDirectoryCommand as any,
  );

  return { command, db };
}

describe('cascadeMovementMarkToDescendants', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls db.execute with a recursive CTE containing WITH RECURSIVE, UNION ALL, and UPDATE', async () => {
    const { command, db } = createCommand();

    await (command as any).cascadeMovementMarkToDescendants({ userProfileId: USER_PROFILE_ID });

    expect(db.execute).toHaveBeenCalledOnce();

    const sqlArg = db.execute.mock.calls[0]?.[0];
    const sqlString: string = sqlArg?.queryChunks
      ? sqlArg.queryChunks
          .map((chunk: any) => (typeof chunk === 'string' ? chunk : String(chunk.value ?? '')))
          .join('')
      : String(sqlArg);

    expect(sqlString).toMatch(/WITH RECURSIVE/i);
    expect(sqlString).toMatch(/UNION ALL/i);
    expect(sqlString).toMatch(/UPDATE/i);
  });

  it('passes userProfileId as an interpolated value in db.execute', async () => {
    const { command, db } = createCommand();

    await (command as any).cascadeMovementMarkToDescendants({ userProfileId: USER_PROFILE_ID });

    expect(db.execute).toHaveBeenCalledOnce();

    const sqlArg = db.execute.mock.calls[0]?.[0];
    // Drizzle sql`` template tag stores interpolated values directly in queryChunks
    const chunks: unknown[] = sqlArg?.queryChunks ?? [];
    expect(chunks).toContain(USER_PROFILE_ID);
  });

  it('db.execute is called during run() after upsertDirectories', async () => {
    const { command, db } = createCommand();

    await command.run({ toString: () => USER_PROFILE_ID } as any);

    expect(db.execute).toHaveBeenCalledOnce();

    const sqlArg = db.execute.mock.calls[0]?.[0];
    const chunks: unknown[] = sqlArg?.queryChunks ?? [];
    expect(chunks).toContain(USER_PROFILE_ID);
  });
});
