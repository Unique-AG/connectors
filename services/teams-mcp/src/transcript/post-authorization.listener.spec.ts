import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MicrosoftConfig } from '~/config';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { PostAuthorizationListener } from './post-authorization.listener';
import type { SubscriptionCreateService } from './subscription-create.service';

const userProfileId = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';

const expectedTypeId = () => convertUserProfileIdToTypeId(userProfileId);

const makeListener = (
  autoStartIngestion: boolean,
  subscriptionCreate: Pick<SubscriptionCreateService, 'enqueueSubscriptionRequested'>,
) => {
  const config = { autoStartIngestion } as unknown as MicrosoftConfig;
  return new PostAuthorizationListener(config, subscriptionCreate as SubscriptionCreateService);
};

const userAuthorizedEvent = (id: string) => ({
  type: 'unique.teams-mcp.auth.user-authorized' as const,
  payload: { userProfileId: id },
});

describe('PostAuthorizationListener', () => {
  let mockSubscriptionCreate: { enqueueSubscriptionRequested: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    mockSubscriptionCreate = {
      enqueueSubscriptionRequested: vi.fn().mockResolvedValue(undefined),
    };
    vi.clearAllMocks();
  });

  it('enqueues a subscription request with the converted id when the flag is on', async () => {
    const listener = makeListener(true, mockSubscriptionCreate);

    await listener.onUserAuthorized(userAuthorizedEvent(userProfileId));

    expect(mockSubscriptionCreate.enqueueSubscriptionRequested).toHaveBeenCalledOnce();
    expect(mockSubscriptionCreate.enqueueSubscriptionRequested).toHaveBeenCalledWith(
      expectedTypeId(),
    );
  });

  it('does nothing when the flag is off', async () => {
    const listener = makeListener(false, mockSubscriptionCreate);

    await listener.onUserAuthorized(userAuthorizedEvent(userProfileId));

    expect(mockSubscriptionCreate.enqueueSubscriptionRequested).not.toHaveBeenCalled();
  });

  it('does not rethrow when enqueue throws', async () => {
    mockSubscriptionCreate.enqueueSubscriptionRequested.mockRejectedValue(
      new Error('enqueue failed'),
    );
    const listener = makeListener(true, mockSubscriptionCreate);

    await expect(
      listener.onUserAuthorized(userAuthorizedEvent(userProfileId)),
    ).resolves.toBeUndefined();

    expect(mockSubscriptionCreate.enqueueSubscriptionRequested).toHaveBeenCalledWith(
      expectedTypeId(),
    );
  });
});
