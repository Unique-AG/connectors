import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { OpenEmailQuery } from '../open-email.query';

const graphMessage = {
  id: 'msg-1',
  subject: 'Offer',
  body: { content: 'Hello' },
  toRecipients: [],
  ccRecipients: [],
};

describe('OpenEmailQuery', () => {
  let graphRequest: { header: Mock; select: Mock; expand: Mock; get: Mock };
  let api: Mock;
  let getContentById: Mock;
  let instance: OpenEmailQuery;

  const run = () => instance.run({ userProfileId: 'user-1', id: 'msg-1' });

  beforeEach(() => {
    graphRequest = {
      header: vi.fn().mockReturnThis(),
      select: vi.fn().mockReturnThis(),
      expand: vi.fn().mockReturnThis(),
      get: vi.fn().mockResolvedValue(graphMessage),
    };
    api = vi.fn().mockReturnValue(graphRequest);
    getContentById = vi.fn();
    instance = new OpenEmailQuery(
      { createClientForUser: vi.fn().mockReturnValue({ api }) } as never,
      { content: { getContentById } } as never,
    );
  });

  it('selects the draft flag and expands the attachment names', async () => {
    await run();

    expect(graphRequest.select).toHaveBeenCalledWith(expect.stringContaining('isDraft'));
    expect(graphRequest.expand).toHaveBeenCalledWith('attachments($select=name,size,isInline)');
    expect(graphRequest.header).toHaveBeenCalledWith('Prefer', 'outlook.body-content-type="text"');
  });

  it('encodes immutable message and folder ids that contain a slash', async () => {
    await instance.run({
      userProfileId: 'user-1',
      id: 'AAk/msg=',
      mailbox: 'shared@example.com',
      folderId: 'AQMk/folder+1=',
      idIsImmutable: true,
    });

    expect(api).toHaveBeenCalledWith(
      '/users/shared@example.com/mailFolders/AQMk-folder+1=/messages/AAk-msg=',
    );
  });

  it('reads a shared mailbox message without a folder from the mailbox messages', async () => {
    await instance.run({
      userProfileId: 'user-1',
      id: 'AAk/draft=',
      mailbox: 'shared@example.com',
      idIsImmutable: true,
    });

    expect(api).toHaveBeenCalledWith('/users/shared@example.com/messages/AAk-draft=');
  });

  it('returns the matched chunks next to the Graph body', async () => {
    getContentById.mockResolvedValue({
      id: 'cont-1',
      chunks: [
        { id: 'chunk-kept', order: 2, text: 'attachment clause' },
        { id: 'chunk-other', order: 1, text: 'the rest of the email' },
      ],
    });

    const result = await instance.run({
      userProfileId: 'user-1',
      id: 'msg-1',
      bodyContentType: 'html',
      uniqueContentId: 'cont-1',
      chunkIds: ['chunk-kept'],
    });

    expect(getContentById).toHaveBeenCalledWith({ contentId: 'cont-1' });
    expect(result.text).toBe('Hello');
    expect(result.bodyContentType).toBe('html');
    expect(result.chunks).toBe('attachment clause');
  });

  it('returns the Graph body without chunks when the ingested email cannot be read', async () => {
    getContentById.mockRejectedValue(new Error('Unique API Content not found'));

    const result = await instance.run({
      userProfileId: 'user-1',
      id: 'msg-1',
      uniqueContentId: 'cont-1',
      chunkIds: ['chunk-kept'],
    });

    expect(result.text).toBe('Hello');
    expect(result.chunks).toBeUndefined();
  });

  it('does not load ingested chunks when the params have none', async () => {
    const result = await run();

    expect(getContentById).not.toHaveBeenCalled();
    expect(result.chunks).toBeUndefined();
  });

  it('requests the HTML body when editing a draft', async () => {
    const result = await instance.run({
      userProfileId: 'user-1',
      id: 'msg-1',
      idIsImmutable: true,
      bodyContentType: 'html',
    });

    expect(graphRequest.header).toHaveBeenCalledWith(
      'Prefer',
      'outlook.body-content-type="html", IdType="ImmutableId"',
    );
    expect(result.bodyContentType).toBe('html');
    expect(result.text).toBe('Hello');
  });

  it('exposes a draft with its attachments', async () => {
    graphRequest.get.mockResolvedValue({
      ...graphMessage,
      isDraft: true,
      hasAttachments: true,
      attachments: [{ name: 'offer.pdf', size: 10, isInline: false }],
    });

    const { metadata } = await run();

    expect(metadata).toMatchObject({
      isDraft: true,
      hasAttachments: true,
      attachments: [{ name: 'offer.pdf', size: 10, isInline: false }],
    });
  });

  it('marks a message without the draft flag as not a draft', async () => {
    const { metadata } = await run();

    expect(metadata).toMatchObject({ isDraft: false, attachments: [] });
  });
});
