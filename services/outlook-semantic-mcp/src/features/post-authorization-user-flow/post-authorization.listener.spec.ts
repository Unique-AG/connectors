import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type AppConfig, McpBackendType } from '~/config';
import type { IsInboxDeletingQuery } from '~/features/delete-inbox/is-inbox-deleting.query';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import type { SyncDirectoriesCommand } from '../directories-sync/sync-directories.command';
import { SubscriptionCreateService } from '../subscriptions/subscription-create.service';
import { PostAuthorizationListener } from './post-authorization.listener';

const makeListener = (
  mcpBackend: McpBackendType,
  subscriptionCreateService: Pick<SubscriptionCreateService, 'subscribe'>,
  syncDirectoriesCommand: Pick<SyncDirectoriesCommand, 'run'>,
) => {
  const config = { mcpBackend } as unknown as AppConfig;
  const isInboxDeleting = { run: vi.fn().mockResolvedValue(false) };
  return new PostAuthorizationListener(
    config,
    syncDirectoriesCommand as unknown as SyncDirectoriesCommand,
    subscriptionCreateService as SubscriptionCreateService,
    isInboxDeleting as unknown as IsInboxDeletingQuery,
  );
};

const userAuthorizedEvent = (userProfileId: string) => ({
  type: 'unique.outlook-semantic-mcp.auth.user-authorized' as const,
  payload: { userProfileId },
});

describe('PostAuthorizationListener', () => {
  const userProfileId = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
  let mockSubscriptionCreateService: { subscribe: ReturnType<typeof vi.fn> };
  let mockSyncDirectoriesCommand: { run: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    mockSubscriptionCreateService = {
      subscribe: vi.fn().mockResolvedValue({ status: 'created' }),
    };
    mockSyncDirectoriesCommand = {
      run: vi.fn().mockResolvedValue(undefined),
    };
    vi.clearAllMocks();
  });

  describe('MicrosoftGraphAndUniqueApi backend', () => {
    it('calls subscribe with the converted userProfileId', async () => {
      const listener = makeListener(
        McpBackendType.MicrosoftGraphAndUniqueApi,
        mockSubscriptionCreateService,
        mockSyncDirectoriesCommand,
      );

      await listener.onUserAuthorized(userAuthorizedEvent(userProfileId));

      expect(mockSubscriptionCreateService.subscribe).toHaveBeenCalledOnce();
      expect(mockSubscriptionCreateService.subscribe).toHaveBeenCalledWith(
        convertUserProfileIdToTypeId(userProfileId),
      );
    });

    it('does not rethrow when subscribe throws', async () => {
      mockSubscriptionCreateService.subscribe.mockRejectedValue(new Error('subscription failed'));
      const listener = makeListener(
        McpBackendType.MicrosoftGraphAndUniqueApi,
        mockSubscriptionCreateService,
        mockSyncDirectoriesCommand,
      );

      await expect(
        listener.onUserAuthorized(userAuthorizedEvent(userProfileId)),
      ).resolves.toBeUndefined();

      expect(mockSubscriptionCreateService.subscribe).toHaveBeenCalledWith(
        convertUserProfileIdToTypeId(userProfileId),
      );
    });
  });

  describe('MicrosoftGraph backend', () => {
    it('calls syncDirectoriesCommand with the converted userProfileId', async () => {
      const listener = makeListener(
        McpBackendType.MicrosoftGraph,
        mockSubscriptionCreateService,
        mockSyncDirectoriesCommand,
      );

      await listener.onUserAuthorized(userAuthorizedEvent(userProfileId));

      expect(mockSyncDirectoriesCommand.run).toHaveBeenCalledOnce();
      expect(mockSyncDirectoriesCommand.run).toHaveBeenCalledWith(
        convertUserProfileIdToTypeId(userProfileId),
      );
      expect(mockSubscriptionCreateService.subscribe).not.toHaveBeenCalled();
    });
  });
});
