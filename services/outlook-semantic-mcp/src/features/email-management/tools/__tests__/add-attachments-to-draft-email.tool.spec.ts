import type { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import type { Context } from '@unique-ag/mcp-server-module';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import type { DraftState } from '../../get-draft-state.query';
import { AddAttachmentsToDraftEmailTool } from '../add-attachments-to-draft-email.tool';

vi.mock('~/utils/extract-user-profile-id', () => ({
  extractUserProfileId: () => ({ toString: () => 'user-1' }),
}));

const DRAFT_STATE: DraftState = { status: 'draft', subject: 'Offer', attachments: [] };
const request = {} as McpAuthenticatedRequest;
const context = { mcpRequest: { params: { _meta: { chatId: 'chat-1' } } } } as unknown as Context;
const attachments = [
  { fileName: 'a.pdf', data: 'unique://content/cont_1' },
  { fileName: 'b.pdf', data: 'unique://content/cont_2' },
];

describe('AddAttachmentsToDraftEmailTool', () => {
  let getDraftStateQuery: { run: Mock };
  let addCommand: { run: Mock };
  let tool: AddAttachmentsToDraftEmailTool;

  beforeEach(() => {
    getDraftStateQuery = { run: vi.fn().mockResolvedValue(DRAFT_STATE) };
    addCommand = { run: vi.fn().mockResolvedValue({ attachmentsFailed: [] }) };
    tool = new AddAttachmentsToDraftEmailTool(getDraftStateQuery as never, addCommand as never);
  });

  it('adds the attachments to the draft', async () => {
    const result = await tool.addAttachments(
      { draftId: 'draft-1', mailbox: 'shared@example.com', attachments },
      context,
      request,
    );

    expect(result).toEqual({ success: true, message: 'Attachments added to the draft.' });
    expect(addCommand.run).toHaveBeenCalledWith(expect.anything(), {
      draftId: 'draft-1',
      attachments,
      chatId: 'chat-1',
      mailbox: 'shared@example.com',
    });
  });

  it('does not upload when the message is no longer a draft', async () => {
    getDraftStateQuery.run.mockResolvedValue({ status: 'failed', message: 'Already sent.' });

    const result = await tool.addAttachments({ draftId: 'sent-1', attachments }, context, request);

    expect(result).toEqual({ success: false, message: 'Already sent.' });
    expect(addCommand.run).not.toHaveBeenCalled();
  });

  it('reports success with the failures when only some attachments fail', async () => {
    const attachmentsFailed = [{ fileName: 'b.pdf', reason: 'Unrecognised attachment type' }];
    addCommand.run.mockResolvedValue({ attachmentsFailed });

    const result = await tool.addAttachments({ draftId: 'draft-1', attachments }, context, request);

    expect(result).toEqual({
      success: true,
      message: 'Some attachments could not be added to the draft.',
      attachmentsFailed,
    });
  });

  it('reports failure when no attachment could be added', async () => {
    const attachmentsFailed = attachments.map(({ fileName }) => ({ fileName, reason: 'nope' }));
    addCommand.run.mockResolvedValue({ attachmentsFailed });

    const result = await tool.addAttachments({ draftId: 'draft-1', attachments }, context, request);

    expect(result).toEqual({
      success: false,
      message: 'No attachment could be added to the draft.',
      attachmentsFailed,
    });
  });
});
