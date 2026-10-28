import { describe, expect, it, type Mock, vi } from 'vitest';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { RemoveAttachmentsFromDraftEmailCommand } from '../remove-attachments-from-draft-email.command';

const USER_PROFILE_ID = { toString: () => 'user-1' } as unknown as UserProfileTypeID;

function makeCommand(deleteImpl: Mock = vi.fn().mockResolvedValue(undefined)) {
  const graphRequest = { header: vi.fn().mockReturnThis(), delete: deleteImpl };
  const api = vi.fn().mockReturnValue(graphRequest);
  const command = new RemoveAttachmentsFromDraftEmailCommand({
    createClientForUser: vi.fn().mockReturnValue({ api }),
  } as unknown as GraphClientFactory);
  return { command, api, graphRequest };
}

describe('RemoveAttachmentsFromDraftEmailCommand', () => {
  it('deletes each attachment from the draft', async () => {
    const { command, api } = makeCommand();

    const result = await command.run(USER_PROFILE_ID, {
      draftId: 'draft-1',
      attachments: [
        { id: 'att-1', name: 'a.pdf' },
        { id: 'att-2', name: 'b.pdf' },
      ],
    });

    expect(result).toEqual({ removed: ['a.pdf', 'b.pdf'], failed: [] });
    expect(api).toHaveBeenCalledWith('/me/messages/draft-1/attachments/att-1');
    expect(api).toHaveBeenCalledWith('/me/messages/draft-1/attachments/att-2');
  });

  it('targets the shared mailbox and applies the ImmutableId header', async () => {
    const { command, api, graphRequest } = makeCommand();

    await command.run(USER_PROFILE_ID, {
      draftId: 'immutable-1',
      idIsImmutable: true,
      mailbox: 'shared@example.com',
      attachments: [{ id: 'att-1', name: 'a.pdf' }],
    });

    expect(api).toHaveBeenCalledWith(
      '/users/shared@example.com/messages/immutable-1/attachments/att-1',
    );
    expect(graphRequest.header).toHaveBeenCalledWith('Prefer', 'IdType="ImmutableId"');
  });

  it('keeps going and reports the attachments that failed', async () => {
    const deleteImpl = vi
      .fn()
      .mockRejectedValueOnce(new Error('locked'))
      .mockResolvedValueOnce(undefined);
    const { command } = makeCommand(deleteImpl);

    const result = await command.run(USER_PROFILE_ID, {
      draftId: 'draft-1',
      attachments: [
        { id: 'att-1', name: 'a.pdf' },
        { id: 'att-2', name: 'b.pdf' },
      ],
    });

    expect(result).toEqual({
      removed: ['b.pdf'],
      failed: [{ fileName: 'a.pdf', reason: 'locked' }],
    });
  });
});
