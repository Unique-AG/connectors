/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */

import type { UniqueApiClient } from '@unique-ag/unique-api';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ExecuteInboxDeletionCommand } from '../execute-inbox-deletion.command';

const userProfileId = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const providerUserId = 'provider-user-id-1';

const makeCommand = (deps: { subscriptionRemove?: any; db?: any; uniqueApi?: any }) => {
  const subscriptionRemove = deps.subscriptionRemove ?? {
    removeByUserProfileId: vi.fn().mockResolvedValue(undefined),
  };
  return new ExecuteInboxDeletionCommand(
    subscriptionRemove,
    deps.db,
    deps.uniqueApi as UniqueApiClient,
  );
};

const makeChainableUpdate = () => ({
  set: vi.fn().mockReturnThis(),
  where: vi.fn().mockReturnThis(),
  returning: vi.fn().mockResolvedValue([]),
});

const makeChainableDelete = () => ({
  where: vi.fn().mockReturnThis(),
  execute: vi.fn().mockResolvedValue(undefined),
});

describe('ExecuteInboxDeletionCommand', () => {
  let mockDb: any;
  let mockUniqueApi: any;

  beforeEach(() => {
    vi.clearAllMocks();

    mockDb = {
      query: {
        userProfiles: {
          findFirst: vi.fn().mockResolvedValue({ id: userProfileId, providerUserId }),
        },
        inboxConfigurations: {
          findFirst: vi.fn().mockResolvedValue({
            userProfileId,
            deletingInboxStartedAt: new Date(),
            deletingHeartbeatAt: null,
          }),
        },
      },
      update: vi.fn().mockReturnValue(makeChainableUpdate()),
      delete: vi.fn().mockReturnValue(makeChainableDelete()),
    };

    mockUniqueApi = {
      scopes: {
        getByExternalId: vi.fn().mockResolvedValue({ id: 'scope-id-1' }),
        delete: vi.fn().mockResolvedValue(undefined),
      },
      files: {
        getIdsByScope: vi.fn().mockResolvedValueOnce(['id1', 'id2']).mockResolvedValueOnce([]),
        deleteByIds: vi.fn().mockResolvedValue(2),
      },
    };
  });

  it('deletes files in batches and updates heartbeat after each', async () => {
    const command = makeCommand({ db: mockDb, uniqueApi: mockUniqueApi });

    await command.run(userProfileId);

    expect(mockUniqueApi.files.deleteByIds).toHaveBeenCalledOnce();
    expect(mockUniqueApi.files.deleteByIds).toHaveBeenCalledWith(['id1', 'id2']);
    // 4 heartbeat updates: after subscription removal, after file batch, after directoriesSync, after directories
    expect(mockDb.update).toHaveBeenCalledTimes(4);
  });

  it('deletes inboxConfigurations row on completion', async () => {
    const command = makeCommand({ db: mockDb, uniqueApi: mockUniqueApi });

    await command.run(userProfileId);

    // Deletes: directoriesSync, directories, inboxConfigurations (3 calls total)
    expect(mockDb.delete).toHaveBeenCalledTimes(3);
  });

  it('treats missing scope as already deleted and proceeds to cleanup', async () => {
    mockUniqueApi.scopes.getByExternalId.mockResolvedValue(null);

    const command = makeCommand({ db: mockDb, uniqueApi: mockUniqueApi });

    await command.run(userProfileId);

    expect(mockUniqueApi.files.deleteByIds).not.toHaveBeenCalled();
    expect(mockDb.delete).toHaveBeenCalled();
  });

  it('returns without processing when user profile not found', async () => {
    mockDb.query.userProfiles.findFirst.mockResolvedValue(undefined);

    const command = makeCommand({ db: mockDb, uniqueApi: mockUniqueApi });

    await command.run(userProfileId);

    expect(mockDb.delete).not.toHaveBeenCalled();
  });
});
