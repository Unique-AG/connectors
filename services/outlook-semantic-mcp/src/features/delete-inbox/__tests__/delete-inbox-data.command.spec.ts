/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DeleteInboxDataCommand } from '../delete-inbox-data.command';

const userProfileId = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';

const makeCommand = (deps: { db?: any; amqp?: any }) => {
  const defaultUpdate = {
    set: vi.fn().mockReturnThis(),
    where: vi.fn().mockReturnThis(),
    returning: vi.fn().mockResolvedValue([{ userProfileId }]),
  };
  const db = deps.db ?? { update: vi.fn().mockReturnValue(defaultUpdate) };
  const amqp = deps.amqp ?? { publish: vi.fn().mockResolvedValue(true) };

  return new DeleteInboxDataCommand(db, amqp);
};

describe('DeleteInboxDataCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns deletion-already-in-progress when deletion guard is already set', async () => {
    const mockUpdate = {
      set: vi.fn().mockReturnThis(),
      where: vi.fn().mockReturnThis(),
      returning: vi.fn().mockResolvedValue([]),
    };
    const mockSelect = {
      from: vi.fn().mockReturnThis(),
      where: vi.fn().mockResolvedValue([{ userProfileId }]),
    };
    const db = {
      update: vi.fn().mockReturnValue(mockUpdate),
      select: vi.fn().mockReturnValue(mockSelect),
    };
    const command = makeCommand({ db });

    const result = await command.run(userProfileId);

    expect(result).toBe('deletion-already-in-progress');
    expect(db.update).toHaveBeenCalledOnce();
  });

  it('sets deletingInboxStartedAt, deletingHeartbeatAt, fullSyncVersion and resets sync state', async () => {
    const mockUpdate = {
      set: vi.fn().mockReturnThis(),
      where: vi.fn().mockReturnThis(),
      returning: vi.fn().mockResolvedValue([{ userProfileId }]),
    };
    const db = { update: vi.fn().mockReturnValue(mockUpdate) };

    const command = makeCommand({ db });
    await command.run(userProfileId);

    expect(db.update).toHaveBeenCalledOnce();
    expect(mockUpdate.set).toHaveBeenCalledOnce();
    expect(mockUpdate.returning).toHaveBeenCalledOnce();
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
