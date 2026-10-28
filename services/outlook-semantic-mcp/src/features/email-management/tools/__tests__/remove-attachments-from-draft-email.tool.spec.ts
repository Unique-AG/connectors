import type { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import type { Context } from '@unique-ag/mcp-server-module';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import type { DraftState } from '../../get-draft-state.query';
import { RemoveAttachmentsFromDraftEmailTool } from '../remove-attachments-from-draft-email.tool';

vi.mock('~/utils/extract-user-profile-id', () => ({
  extractUserProfileId: () => ({ toString: () => 'user-1' }),
}));

const DRAFT_STATE: DraftState = {
  status: 'draft',
  subject: 'Offer',
  attachments: [
    { id: 'att-1', name: 'Offer.pdf' },
    { id: 'att-2', name: 'terms.docx' },
  ],
};
const request = {} as McpAuthenticatedRequest;

describe('RemoveAttachmentsFromDraftEmailTool', () => {
  let getDraftStateQuery: { run: Mock };
  let removeCommand: { run: Mock };
  let elicit: Mock;
  let context: Context;
  let tool: RemoveAttachmentsFromDraftEmailTool;

  beforeEach(() => {
    getDraftStateQuery = { run: vi.fn().mockResolvedValue(DRAFT_STATE) };
    removeCommand = {
      run: vi.fn().mockResolvedValue({ removed: ['Offer.pdf'], failed: [] }),
    };
    elicit = vi.fn().mockResolvedValue({ action: 'accept', content: {} });
    context = { elicit } as unknown as Context;
    tool = new RemoveAttachmentsFromDraftEmailTool(
      getDraftStateQuery as never,
      removeCommand as never,
    );
  });

  it('asks the user to confirm, then removes the matched attachments', async () => {
    const result = await tool.removeAttachments(
      { draftId: 'draft-1', fileNames: ['offer.PDF'] },
      context,
      request,
    );

    expect(elicit).toHaveBeenCalledWith(expect.anything(), expect.stringContaining('- Offer.pdf'));
    expect(removeCommand.run).toHaveBeenCalledWith(expect.anything(), {
      draftId: 'draft-1',
      idIsImmutable: undefined,
      mailbox: undefined,
      attachments: [{ id: 'att-1', name: 'Offer.pdf' }],
    });
    expect(result).toEqual({
      success: true,
      message: 'Attachments removed from the draft.',
      removed: ['Offer.pdf'],
    });
  });

  it('removes nothing when the user declines', async () => {
    elicit.mockResolvedValue({ action: 'decline' });

    const result = await tool.removeAttachments(
      { draftId: 'draft-1', fileNames: ['Offer.pdf'] },
      context,
      request,
    );

    expect(result).toEqual({
      success: false,
      message: 'Attachment removal was cancelled. Nothing was removed.',
    });
    expect(removeCommand.run).not.toHaveBeenCalled();
  });

  it('removes nothing when the client cannot show a confirmation prompt', async () => {
    elicit.mockRejectedValue(new Error('Client does not support elicitation'));

    const result = await tool.removeAttachments(
      { draftId: 'draft-1', fileNames: ['Offer.pdf'] },
      context,
      request,
    );

    expect(result.success).toBe(false);
    expect(removeCommand.run).not.toHaveBeenCalled();
  });

  it('lists the draft attachments when a requested name is not on the draft', async () => {
    const result = await tool.removeAttachments(
      { draftId: 'draft-1', fileNames: ['Offer.pdf', 'missing.txt'] },
      context,
      request,
    );

    expect(result).toEqual({
      success: false,
      message:
        'The draft has no attachment named "missing.txt". Nothing was removed. The draft\'s attachments are: "Offer.pdf", "terms.docx".',
    });
    expect(elicit).not.toHaveBeenCalled();
  });

  it('does not prompt when the message is no longer a draft', async () => {
    getDraftStateQuery.run.mockResolvedValue({ status: 'failed', message: 'Already sent.' });

    const result = await tool.removeAttachments(
      { draftId: 'sent-1', fileNames: ['Offer.pdf'] },
      context,
      request,
    );

    expect(result).toEqual({ success: false, message: 'Already sent.' });
    expect(elicit).not.toHaveBeenCalled();
  });

  it('reports the attachments Graph failed to remove', async () => {
    removeCommand.run.mockResolvedValue({
      removed: [],
      failed: [{ fileName: 'Offer.pdf', reason: 'locked' }],
    });

    const result = await tool.removeAttachments(
      { draftId: 'draft-1', fileNames: ['Offer.pdf'] },
      context,
      request,
    );

    expect(result).toEqual({
      success: false,
      message: 'Some attachments could not be removed from the draft.',
      removed: [],
      failed: [{ fileName: 'Offer.pdf', reason: 'locked' }],
    });
  });
});
