import { beforeEach, describe, expect, it, vi } from 'vitest';
import { folderPathsCacheKey, GetFolderPathsQuery } from '../get-folder-paths.query';

interface MockDirectory {
  id: string;
  providerDirectoryId: string;
  displayName: string;
  parentId: string | null;
  userProfileId: string;
}

const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';

const inboxDir: MockDirectory = {
  id: 'dir-001',
  providerDirectoryId: 'provider-inbox',
  displayName: 'Inbox',
  parentId: null,
  userProfileId: USER_PROFILE_ID,
};

const workDir: MockDirectory = {
  id: 'dir-002',
  providerDirectoryId: 'provider-work',
  displayName: 'Work',
  parentId: 'dir-001',
  userProfileId: USER_PROFILE_ID,
};

const projectsDir: MockDirectory = {
  id: 'dir-003',
  providerDirectoryId: 'provider-projects',
  displayName: 'Projects',
  parentId: 'dir-002',
  userProfileId: USER_PROFILE_ID,
};

function createMockDb(dirs: MockDirectory[]) {
  return {
    query: {
      directories: {
        findMany: vi.fn().mockResolvedValue(dirs),
      },
    },
  };
}

function createMockCacheManager(cachedValue: Record<string, string> | null = null) {
  return {
    get: vi.fn().mockResolvedValue(cachedValue),
    set: vi.fn().mockResolvedValue(undefined),
  };
}

function createQuery(dirs: MockDirectory[], cachedValue: Record<string, string> | null = null) {
  // biome-ignore lint/suspicious/noExplicitAny: test mock does not implement full DrizzleDatabase
  const db = createMockDb(dirs) as any;
  const cacheManager = createMockCacheManager(cachedValue);
  // biome-ignore lint/suspicious/noExplicitAny: test mock does not implement full Cache interface
  const query = new GetFolderPathsQuery(db, cacheManager as any);
  return { query, db, cacheManager };
}

describe('folderPathsCacheKey', () => {
  it('returns the expected cache key string for a user profile id', () => {
    expect(folderPathsCacheKey(USER_PROFILE_ID)).toBe(`folder-paths:${USER_PROFILE_ID}`);
  });
});

describe('GetFolderPathsQuery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('path building', () => {
    it('maps a root directory to its display name', async () => {
      const { query } = createQuery([inboxDir]);

      const result = await query.run(USER_PROFILE_ID);

      expect(result).toEqual({ 'provider-inbox': '/Inbox' });
    });

    it('maps a child directory to a slash-joined path', async () => {
      const { query } = createQuery([inboxDir, workDir]);

      const result = await query.run(USER_PROFILE_ID);

      expect(result).toEqual({
        'provider-inbox': '/Inbox',
        'provider-work': '/Inbox/Work',
      });
    });

    it('maps a deeply nested directory to a fully traversed path', async () => {
      const { query } = createQuery([inboxDir, workDir, projectsDir]);

      const result = await query.run(USER_PROFILE_ID);

      expect(result).toEqual({
        'provider-inbox': '/Inbox',
        'provider-work': '/Inbox/Work',
        'provider-projects': '/Inbox/Work/Projects',
      });
    });

    it('handles multiple root-level directories', async () => {
      const sentDir: MockDirectory = {
        id: 'dir-004',
        providerDirectoryId: 'provider-sent',
        displayName: 'Sent Items',
        parentId: null,
        userProfileId: USER_PROFILE_ID,
      };

      const { query } = createQuery([inboxDir, sentDir]);

      const result = await query.run(USER_PROFILE_ID);

      expect(result).toEqual({
        'provider-inbox': '/Inbox',
        'provider-sent': '/Sent Items',
      });
    });

    it('returns an empty record when there are no directories', async () => {
      const { query } = createQuery([]);

      const result = await query.run(USER_PROFILE_ID);

      expect(result).toEqual({});
    });
  });

  describe('cache behaviour', () => {
    it('returns cached value on cache hit without querying the db', async () => {
      const cached = { 'provider-inbox': '/Inbox' };
      const { query, db, cacheManager } = createQuery([inboxDir], cached);

      const result = await query.run(USER_PROFILE_ID);

      expect(result).toEqual(cached);
      expect(cacheManager.get).toHaveBeenCalledOnce();
      expect(db.query.directories.findMany).not.toHaveBeenCalled();
      expect(cacheManager.set).not.toHaveBeenCalled();
    });

    it('queries the db and populates cache on cache miss', async () => {
      const { query, db, cacheManager } = createQuery([inboxDir]);

      const result = await query.run(USER_PROFILE_ID);

      expect(cacheManager.get).toHaveBeenCalledOnce();
      expect(db.query.directories.findMany).toHaveBeenCalledOnce();
      expect(cacheManager.set).toHaveBeenCalledOnce();
      expect(cacheManager.set).toHaveBeenCalledWith(
        folderPathsCacheKey(USER_PROFILE_ID),
        result,
        600_000,
      );
    });

    it('uses the correct cache key derived from the user profile id', async () => {
      const { query, cacheManager } = createQuery([]);

      await query.run(USER_PROFILE_ID);

      expect(cacheManager.get).toHaveBeenCalledWith(folderPathsCacheKey(USER_PROFILE_ID));
    });
  });
});
