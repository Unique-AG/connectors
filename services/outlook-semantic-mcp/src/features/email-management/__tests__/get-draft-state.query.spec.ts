import { describe, expect, it, type Mock, vi } from 'vitest';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { GetDraftStateQuery } from '../get-draft-state.query';

interface MockGraphRequest {
  select: Mock;
  expand: Mock;
  header: Mock;
  get: Mock;
}

function makeQuery(response: unknown | Error) {
  const graphRequest: MockGraphRequest = {
    select: vi.fn().mockReturnThis(),
    expand: vi.fn().mockReturnThis(),
    header: vi.fn().mockReturnThis(),
    get:
      response instanceof Error
        ? vi.fn().mockRejectedValue(response)
        : vi.fn().mockResolvedValue(response),
  };
  const api = vi.fn().mockReturnValue(graphRequest);
  const query = new GetDraftStateQuery({
    createClientForUser: vi.fn().mockReturnValue({ api }),
  } as unknown as GraphClientFactory);
  return { query, api, graphRequest };
}

describe('GetDraftStateQuery', () => {
  it('returns the subject and attachments of a draft', async () => {
    const { query, api, graphRequest } = makeQuery({
      isDraft: true,
      subject: 'Offer',
      attachments: [
        { id: 'att-1', name: 'offer.pdf', isInline: false },
        { id: 'att-2', name: 'logo.png', isInline: true },
        { id: 'att-3', name: null, isInline: null },
      ],
    });

    const result = await query.run({ userProfileId: 'user-1', draftId: 'draft-1' });

    expect(result).toEqual({
      status: 'draft',
      subject: 'Offer',
      attachments: [
        { id: 'att-1', name: 'offer.pdf', isInline: false },
        { id: 'att-2', name: 'logo.png', isInline: true },
      ],
    });
    expect(api).toHaveBeenCalledWith('/me/messages/draft-1');
    expect(graphRequest.header).not.toHaveBeenCalled();
  });

  it('reads from the shared mailbox and applies the ImmutableId header', async () => {
    const { query, api, graphRequest } = makeQuery({ isDraft: true });

    await query.run({
      userProfileId: 'user-1',
      draftId: 'immutable/id',
      idIsImmutable: true,
      mailbox: 'shared@example.com',
    });

    expect(api).toHaveBeenCalledWith('/users/shared@example.com/messages/immutable-id');
    expect(graphRequest.header).toHaveBeenCalledWith('Prefer', 'IdType="ImmutableId"');
  });

  it('reads a draft in a folder of the shared mailbox through that folder', async () => {
    const { query, api } = makeQuery({ isDraft: true });

    await query.run({
      userProfileId: 'user-1',
      draftId: 'draft-1',
      mailbox: 'shared@example.com',
      parentFolderId: 'drafts-folder',
    });

    expect(api).toHaveBeenCalledWith(
      '/users/shared@example.com/mailFolders/drafts-folder/messages/draft-1',
    );
  });

  it('reads a draft whose attachments Graph returns as null', async () => {
    const { query } = makeQuery({ isDraft: true, subject: 'Offer', attachments: null });

    const result = await query.run({ userProfileId: 'user-1', draftId: 'draft-1' });

    expect(result).toEqual({ status: 'draft', subject: 'Offer', attachments: [] });
  });

  it('fails without a state when Graph returned only part of the attachments', async () => {
    const { query } = makeQuery({
      isDraft: true,
      attachments: [{ id: 'att-1', name: 'offer.pdf', isInline: false }],
      'attachments@odata.nextLink':
        'https://graph.microsoft.com/v1.0/me/messages/draft-1/attachments?$skip=20',
    });

    const result = await query.run({ userProfileId: 'user-1', draftId: 'draft-1' });

    expect(result).toMatchObject({
      status: 'failed',
      message: expect.stringContaining('attachment list is incomplete'),
    });
  });

  it('fails when the message is no longer a draft', async () => {
    const { query } = makeQuery({ isDraft: false, subject: 'Sent' });

    const result = await query.run({ userProfileId: 'user-1', draftId: 'sent-1' });

    expect(result).toMatchObject({
      status: 'failed',
      message: expect.stringContaining('no longer a draft'),
    });
  });

  it('fails when Graph cannot return the message', async () => {
    const { query } = makeQuery(new Error('ErrorItemNotFound'));

    const result = await query.run({ userProfileId: 'user-1', draftId: 'gone-1' });

    expect(result).toMatchObject({
      status: 'failed',
      message: expect.stringContaining('Could not read the draft'),
    });
  });
});
