/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import type { SubscriptionRemoveService } from '../../subscriptions/subscription-remove.service';
import { DeleteInboxDataCommand } from '../delete-inbox-data.command';

const userProfileId = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';

const makeCommand = (deps: {
  subscriptionRemove?: Partial<SubscriptionRemoveService>;
  db?: any;
  amqp?: any;
}) => {
  const defaultUpdate = {
    set: vi.fn().mockReturnThis(),
    where: vi.fn().mockReturnThis(),
    execute: vi.fn().mockResolvedValue(undefined),
  };
  const subscriptionRemove = {
    removeByUserProfileId: vi.fn().mockResolvedValue({ status: 'removed', subscription: null }),
    ...deps.subscriptionRemove,
  };
  const db = deps.db ?? { update: vi.fn().mockReturnValue(defaultUpdate) };
  const amqp = deps.amqp ?? { publish: vi.fn().mockResolvedValue(true) };

  return new DeleteInboxDataCommand(
    subscriptionRemove as unknown as SubscriptionRemoveService,
    db,
    amqp,
  );
};

describe('DeleteInboxDataCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('removes the graph subscription before setting guard', async () => {
    const subscriptionRemove = {
      removeByUserProfileId: vi.fn().mockResolvedValue({ status: 'removed', subscription: null }),
    };
    const mockUpdate = {
      set: vi.fn().mockReturnThis(),
      where: vi.fn().mockReturnThis(),
      execute: vi.fn().mockResolvedValue(undefined),
    };
    const db = { update: vi.fn().mockReturnValue(mockUpdate) };
    const amqp = { publish: vi.fn().mockResolvedValue(true) };

    const command = makeCommand({ subscriptionRemove, db, amqp });
    await command.run(userProfileId);

    expect(subscriptionRemove.removeByUserProfileId).toHaveBeenCalledOnce();
    expect(subscriptionRemove.removeByUserProfileId).toHaveBeenCalledWith(
      convertUserProfileIdToTypeId(userProfileId),
    );
  });

  it('sets deletingInboxStartedAt, deletingHeartbeatAt, fullSyncVersion and resets sync state', async () => {
    const mockUpdate = {
      set: vi.fn().mockReturnThis(),
      where: vi.fn().mockReturnThis(),
      execute: vi.fn().mockResolvedValue(undefined),
    };
    const db = { update: vi.fn().mockReturnValue(mockUpdate) };

    const command = makeCommand({ db });
    await command.run(userProfileId);

    expect(db.update).toHaveBeenCalledOnce();
    expect(mockUpdate.set).toHaveBeenCalledOnce();
    expect(mockUpdate.execute).toHaveBeenCalledOnce();
  });

  it('publishes delete-inbox-data.execute event', async () => {
    const amqp = { publish: vi.fn().mockResolvedValue(true) };
    const command = makeCommand({ amqp });

    await command.run(userProfileId);

    expect(amqp.publish).toHaveBeenCalledOnce();
    expect(amqp.publish).toHaveBeenCalledWith(
      MAIN_EXCHANGE.name,
      'unique.outlook-semantic-mcp.delete-inbox-data.execute',
      expect.objectContaining({
        type: 'unique.outlook-semantic-mcp.delete-inbox-data.execute',
        payload: { userProfileId },
      }),
    );
  });

  it('throws when amqp publish returns false', async () => {
    const amqp = { publish: vi.fn().mockResolvedValue(false) };
    const command = makeCommand({ amqp });

    await expect(command.run(userProfileId)).rejects.toThrow();
  });
});
