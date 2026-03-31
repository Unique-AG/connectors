/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UpsertDirectoryCommand } from './upsert-directory.command';

const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';

const mockDirectory = {
  id: 'provider-folder-1',
  displayName: 'Inbox',
  type: 'User Defined Directory' as const,
};

const storedDirectory = {
  id: 'dir-001',
  providerDirectoryId: 'provider-folder-1',
  displayName: 'Inbox',
  parentId: 'parent-1',
  userProfileId: USER_PROFILE_ID,
};

function createMockDb(returnedDirectory = storedDirectory) {
  const insertChain = {
    onConflictDoNothing: vi.fn().mockReturnThis(),
    onConflictDoUpdate: vi.fn().mockReturnThis(),
    execute: vi.fn().mockResolvedValue(undefined),
  };

  return {
    insert: vi.fn().mockReturnValue({ values: vi.fn().mockReturnValue(insertChain) }),
    query: {
      directories: {
        findFirst: vi.fn().mockResolvedValue(returnedDirectory),
      },
    },
    _insertChain: insertChain,
  };
}

function createMockCacheManager() {
  return { del: vi.fn().mockResolvedValue(undefined) };
}

function createCommand(returnedDirectory = storedDirectory) {
  const db = createMockDb(returnedDirectory);
  const cacheManager = createMockCacheManager();
  const command = new UpsertDirectoryCommand(db as any, cacheManager as any);
  return { command, db, cacheManager };
}

describe('UpsertDirectoryCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('uses onConflictDoUpdate when updateOnConflict=true', async () => {
    const { command, db } = createCommand();

    await command.run({
      parentId: 'parent-1',
      userProfileId: USER_PROFILE_ID,
      directory: mockDirectory,
      updateOnConflict: true,
    });

    expect(db._insertChain.onConflictDoUpdate).toHaveBeenCalledOnce();
    expect(db._insertChain.onConflictDoNothing).not.toHaveBeenCalled();
  });

  it('uses onConflictDoNothing when updateOnConflict=false', async () => {
    const { command, db } = createCommand();

    await command.run({
      parentId: 'parent-1',
      userProfileId: USER_PROFILE_ID,
      directory: mockDirectory,
      updateOnConflict: false,
    });

    expect(db._insertChain.onConflictDoNothing).toHaveBeenCalledOnce();
    expect(db._insertChain.onConflictDoUpdate).not.toHaveBeenCalled();
  });

  it('returns the directory from the post-upsert read', async () => {
    const { command } = createCommand();

    const result = await command.run({
      parentId: 'parent-1',
      userProfileId: USER_PROFILE_ID,
      directory: mockDirectory,
      updateOnConflict: true,
    });

    expect(result).toEqual(storedDirectory);
  });

  it('invalidates the folder paths cache after upsert', async () => {
    const { command, cacheManager } = createCommand();

    await command.run({
      parentId: 'parent-1',
      userProfileId: USER_PROFILE_ID,
      directory: mockDirectory,
      updateOnConflict: true,
    });

    expect(cacheManager.del).toHaveBeenCalledOnce();
  });

  it('includes CASE expressions for parentChangeDetectedAt and directoryMovementResyncCursor in onConflictDoUpdate', async () => {
    const { command, db } = createCommand();

    await command.run({
      parentId: 'parent-1',
      userProfileId: USER_PROFILE_ID,
      directory: mockDirectory,
      updateOnConflict: true,
    });

    const setArg = db._insertChain.onConflictDoUpdate.mock.calls[0]?.[0].set;
    expect(setArg).toHaveProperty('parentChangeDetectedAt');
    expect(setArg).toHaveProperty('directoryMovementResyncCursor');
  });
});
