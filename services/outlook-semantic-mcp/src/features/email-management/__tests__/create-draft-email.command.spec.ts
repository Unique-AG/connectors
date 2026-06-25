import { describe, expect, it, vi } from 'vitest';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { CreateDraftEmailCommand } from '../create-draft-email.command';

const USER_PROFILE_ID = { toString: () => 'user-1' } as unknown as UserProfileTypeID;
const USER_PROFILE = { id: 'user-1', email: 'user@test.com' };

interface MockGraphRequest {
  header: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
}

function makeCommand() {
  const graphRequest: MockGraphRequest = {
    header: vi.fn().mockReturnThis(),
    post: vi.fn().mockResolvedValue({ id: 'draft-1', webLink: 'https://outlook.test/draft' }),
  };

  const graphClientFactory = {
    createClientForUser: vi.fn().mockReturnValue({
      api: vi.fn().mockReturnValue(graphRequest),
    }),
  } as unknown as GraphClientFactory;

  const command = new CreateDraftEmailCommand(
    graphClientFactory,
    { run: vi.fn() } as never,
    { run: vi.fn().mockResolvedValue(new Map()) } as never,
    { run: vi.fn().mockResolvedValue(USER_PROFILE) } as never,
  );

  return { command, graphRequest };
}

describe('CreateDraftEmailCommand.createDraft', () => {
  it('applies ImmutableId header when idIsImmutable is true', async () => {
    const { command, graphRequest } = makeCommand();

    const result = await command.createDraft(USER_PROFILE_ID, {
      content: 'Thanks for the update.',
      chatId: null,
      recipientsData: {
        type: 'reply',
        inReplyToMessageId: 'immutable-id-1',
        idIsImmutable: true,
      },
    });

    expect(result).toMatchObject({ success: true, draftId: 'draft-1' });
    expect(graphRequest.header).toHaveBeenCalledWith('Prefer', 'IdType="ImmutableId"');
  });

  it('sends reply content as comment so the quoted thread is preserved', async () => {
    const { command, graphRequest } = makeCommand();

    await command.createDraft(USER_PROFILE_ID, {
      content: 'Thanks for the update.',
      chatId: null,
      recipientsData: {
        type: 'reply',
        inReplyToMessageId: 'immutable-id-1',
        idIsImmutable: true,
      },
    });

    expect(graphRequest.post).toHaveBeenCalledWith({
      comment: '<p>Thanks for the update.</p>\n',
    });
  });

  it('uses top-level mailbox for shared mailbox replies', async () => {
    const api = vi.fn().mockReturnValue({
      header: vi.fn().mockReturnThis(),
      post: vi.fn().mockResolvedValue({ id: 'draft-1' }),
    });
    const command = new CreateDraftEmailCommand(
      { createClientForUser: vi.fn().mockReturnValue({ api }) } as unknown as GraphClientFactory,
      { run: vi.fn() } as never,
      { run: vi.fn().mockResolvedValue(new Map()) } as never,
      { run: vi.fn().mockResolvedValue(USER_PROFILE) } as never,
    );

    await command.createDraft(USER_PROFILE_ID, {
      content: 'Thanks for the update.',
      chatId: null,
      mailbox: 'shared@example.com',
      recipientsData: {
        type: 'reply',
        inReplyToMessageId: 'immutable-id-1',
        idIsImmutable: true,
      },
    });

    expect(api).toHaveBeenCalledWith(
      '/users/shared@example.com/messages/immutable-id-1/createReplyAll',
    );
  });

  it('replaces slashes in reply message IDs for Graph URL paths', async () => {
    const api = vi.fn().mockReturnValue({
      header: vi.fn().mockReturnThis(),
      post: vi.fn().mockResolvedValue({ id: 'draft-1' }),
    });
    const command = new CreateDraftEmailCommand(
      { createClientForUser: vi.fn().mockReturnValue({ api }) } as unknown as GraphClientFactory,
      { run: vi.fn() } as never,
      { run: vi.fn().mockResolvedValue(new Map()) } as never,
      { run: vi.fn().mockResolvedValue(USER_PROFILE) } as never,
    );

    await command.createDraft(USER_PROFILE_ID, {
      content: 'Thanks for the update.',
      chatId: null,
      recipientsData: {
        type: 'reply',
        inReplyToMessageId: 'abc/def',
        idIsImmutable: true,
      },
    });

    expect(api).toHaveBeenCalledWith('/me/messages/abc-def/createReplyAll');
  });
});
