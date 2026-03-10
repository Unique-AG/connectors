/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SubscriptionCreateService } from '../subscription-create.service';
import { PostAuthorizationListener } from './post-authorization.listener';

const makeListener = (subscriptionCreateService: Pick<SubscriptionCreateService, 'subscribe'>) =>
  new PostAuthorizationListener(subscriptionCreateService as SubscriptionCreateService);

describe('PostAuthorizationListener', () => {
  const userProfileId = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
  let mockSubscriptionCreateService: { subscribe: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    mockSubscriptionCreateService = {
      subscribe: vi.fn().mockResolvedValue({ status: 'created' }),
    };
    vi.clearAllMocks();
  });

  it('calls subscribe with the converted userProfileId', async () => {
    const listener = makeListener(mockSubscriptionCreateService);

    await listener.onUserAuthorized({
      type: 'unique.outlook-semantic-mcp.auth.user-authorized',
      payload: { userProfileId },
    });

    expect(mockSubscriptionCreateService.subscribe).toHaveBeenCalledOnce();
    expect(mockSubscriptionCreateService.subscribe).toHaveBeenCalledWith(
      convertUserProfileIdToTypeId(userProfileId),
    );
  });

  it('does not rethrow when subscribe throws', async () => {
    mockSubscriptionCreateService.subscribe.mockRejectedValue(new Error('subscription failed'));
    const listener = makeListener(mockSubscriptionCreateService);

    await expect(
      listener.onUserAuthorized({
        type: 'unique.outlook-semantic-mcp.auth.user-authorized',
        payload: { userProfileId },
      }),
    ).resolves.toBeUndefined();

    expect(mockSubscriptionCreateService.subscribe).toHaveBeenCalledWith(
      convertUserProfileIdToTypeId(userProfileId),
    );
  });
});
