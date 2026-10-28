import { describe, expect, it, type Mock, vi } from 'vitest';
import { WebLinks } from '~/features/graph-utils/build-web-links.command';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import type { DraftState } from '../get-draft-state.query';
import { UpdateDraftEmailCommand } from '../update-draft-email.command';

const USER_PROFILE_ID = { toString: () => 'user-1' } as unknown as UserProfileTypeID;
const DRAFT_STATE: DraftState = { status: 'draft', subject: 'Offer', attachments: [] };

function makeCommand(draftState: DraftState = DRAFT_STATE) {
  const graphRequest: { header: Mock; patch: Mock } = {
    header: vi.fn().mockReturnThis(),
    patch: vi.fn().mockResolvedValue({ id: 'draft-1', webLink: 'https://outlook.test/draft' }),
  };
  const api = vi.fn().mockReturnValue(graphRequest);
  const getDraftStateQuery = { run: vi.fn().mockResolvedValue(draftState) };
  const webLinks = new WebLinks();
  webLinks.set('user@test.com', 'draft-1', 'https://owa.test/draft');
  const buildWebLinksCommand = { run: vi.fn().mockResolvedValue(webLinks) };

  const command = new UpdateDraftEmailCommand(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as unknown as GraphClientFactory,
    getDraftStateQuery as never,
    buildWebLinksCommand as never,
    { run: vi.fn().mockResolvedValue({ id: 'user-1', email: 'user@test.com' }) } as never,
  );
  return { command, api, graphRequest, getDraftStateQuery, buildWebLinksCommand };
}

describe('UpdateDraftEmailCommand', () => {
  it('patches only the provided fields', async () => {
    const { command, api, graphRequest } = makeCommand();

    const result = await command.run(USER_PROFILE_ID, {
      draftId: 'draft-1',
      subject: 'Offer (final)',
      content: '<p>Thanks <strong>a lot</strong>.</p>',
    });

    expect(result).toEqual({
      success: true,
      draftId: 'draft-1',
      webLink: 'https://owa.test/draft',
      message: 'Draft email updated successfully.',
    });
    expect(api).toHaveBeenCalledWith('/me/messages/draft-1');
    expect(graphRequest.patch).toHaveBeenCalledWith({
      subject: 'Offer (final)',
      body: { contentType: 'HTML', content: '<p>Thanks <strong>a lot</strong>.</p>' },
    });
  });

  it('replaces recipient lists and clears CC with an empty list', async () => {
    const { command, graphRequest } = makeCommand();

    await command.run(USER_PROFILE_ID, {
      draftId: 'draft-1',
      toRecipients: [{ name: 'Ada', email: 'ada@example.com' }],
      ccRecipients: [],
    });

    expect(graphRequest.patch).toHaveBeenCalledWith({
      toRecipients: [{ emailAddress: { address: 'ada@example.com', name: 'Ada' } }],
      ccRecipients: [],
    });
  });

  it('targets the shared mailbox and applies the ImmutableId header', async () => {
    const { command, api, graphRequest, buildWebLinksCommand } = makeCommand();

    await command.run(USER_PROFILE_ID, {
      draftId: 'immutable-1',
      idIsImmutable: true,
      mailbox: 'shared@example.com',
      subject: 'Hi',
    });

    expect(api).toHaveBeenCalledWith('/users/shared@example.com/messages/immutable-1');
    expect(graphRequest.header).toHaveBeenCalledWith('Prefer', 'IdType="ImmutableId"');
    expect(buildWebLinksCommand.run).toHaveBeenCalledWith(
      expect.objectContaining({
        ids: [
          {
            id: 'draft-1',
            isImmutable: true,
            mailbox: 'shared@example.com',
            webLink: 'https://outlook.test/draft',
          },
        ],
      }),
    );
  });

  it('does not patch when the message is no longer a draft', async () => {
    const { command, graphRequest } = makeCommand({ status: 'failed', message: 'Already sent.' });

    const result = await command.run(USER_PROFILE_ID, { draftId: 'sent-1', subject: 'Hi' });

    expect(result).toEqual({ success: false, message: 'Already sent.' });
    expect(graphRequest.patch).not.toHaveBeenCalled();
  });

  it('reports a failed patch', async () => {
    const { command, graphRequest } = makeCommand();
    graphRequest.patch.mockRejectedValue(new Error('boom'));

    const result = await command.run(USER_PROFILE_ID, { draftId: 'draft-1', subject: 'Hi' });

    expect(result).toEqual({
      success: false,
      message: 'Failed to update draft email via Microsoft Graph. Nothing was changed.',
    });
  });
});
