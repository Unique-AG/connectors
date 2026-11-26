import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { BuildWebLinksCommand } from '~/features/graph-utils/build-web-links.command';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { OpenEmailQuery } from '../open-email.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'own@example.com';
const GRAPH_WEB_LINK = 'https://outlook.cloud.microsoft/mail/deeplink/read/msg-1';

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
  let translateImmutableIdsToRestIds: { run: Mock };
  let instance: OpenEmailQuery;

  const run = () => instance.run({ userProfileId: USER_PROFILE_ID, id: 'msg-1' });

  beforeEach(() => {
    graphRequest = {
      header: vi.fn().mockReturnThis(),
      select: vi.fn().mockReturnThis(),
      expand: vi.fn().mockReturnThis(),
      get: vi.fn().mockResolvedValue(graphMessage),
    };
    api = vi.fn().mockReturnValue(graphRequest);
    getContentById = vi.fn();
    translateImmutableIdsToRestIds = { run: vi.fn().mockResolvedValue(new Map()) };
    instance = new OpenEmailQuery(
      { createClientForUser: vi.fn().mockReturnValue({ api }) } as never,
      { content: { getContentById } } as never,
      {
        run: vi.fn().mockResolvedValue({ id: USER_PROFILE_ID.toString(), email: OWN_EMAIL }),
      } as never,
      new BuildWebLinksCommand(translateImmutableIdsToRestIds as never),
    );
  });

  it('returns the subject as title and the Graph web link of an own-mailbox message', async () => {
    graphRequest.get.mockResolvedValue({ ...graphMessage, webLink: GRAPH_WEB_LINK });

    const result = await run();

    expect(result.title).toBe('Offer');
    expect(result.webLink).toBe(GRAPH_WEB_LINK);
    expect(result.metadata).not.toHaveProperty('webLink');
  });

  it.each([null, '', '   '])('titles an email with subject %j "(no subject)"', async (subject) => {
    graphRequest.get.mockResolvedValue({ ...graphMessage, subject });

    const result = await run();

    expect(result.title).toBe('(no subject)');
  });

  it('builds the classic Outlook web link of a shared-mailbox message from its RestId', async () => {
    graphRequest.get.mockResolvedValue({ ...graphMessage, id: 'AAk-msg', webLink: GRAPH_WEB_LINK });
    translateImmutableIdsToRestIds.run.mockResolvedValue(new Map([['AAk-msg', 'AAMk/rest=']]));

    const result = await instance.run({
      userProfileId: USER_PROFILE_ID,
      id: 'AAk-msg',
      mailbox: 'shared@example.com',
      idIsImmutable: true,
    });

    expect(translateImmutableIdsToRestIds.run).toHaveBeenCalledWith({
      userProfileId: USER_PROFILE_ID.toString(),
      ids: ['AAk-msg'],
      ownerEmail: 'shared@example.com',
    });
    expect(result.webLink).toBe(
      'https://outlook.office365.com/owa/?ItemID=AAMk%2Frest%3D&exvsurl=1&viewmodel=ReadMessageItem',
    );
  });

  it('returns no web link when the shared-mailbox id cannot be translated', async () => {
    graphRequest.get.mockResolvedValue({ ...graphMessage, id: 'AAk-msg', webLink: GRAPH_WEB_LINK });

    const result = await instance.run({
      userProfileId: USER_PROFILE_ID,
      id: 'AAk-msg',
      mailbox: 'shared@example.com',
      idIsImmutable: true,
    });

    expect(result.webLink).toBeNull();
  });

  it('returns no web link when Graph sends none', async () => {
    const result = await run();

    expect(result.webLink).toBeNull();
  });

  it('selects the draft flag and expands the attachment names', async () => {
    await run();

    expect(graphRequest.select).toHaveBeenCalledWith(expect.stringContaining('isDraft'));
    expect(graphRequest.expand).toHaveBeenCalledWith('attachments($select=name,size,isInline)');
    expect(graphRequest.header).toHaveBeenCalledWith('Prefer', 'outlook.body-content-type="text"');
  });

  it('encodes immutable message and folder ids that contain a slash', async () => {
    await instance.run({
      userProfileId: USER_PROFILE_ID,
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
      userProfileId: USER_PROFILE_ID,
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
      userProfileId: USER_PROFILE_ID,
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
      userProfileId: USER_PROFILE_ID,
      id: 'msg-1',
      uniqueContentId: 'cont-1',
      chunkIds: ['chunk-kept'],
    });

    expect(result.text).toBe('Hello');
    expect(result.chunks).toBeUndefined();
  });

  it('returns the Graph body without chunks when none of the matched chunks remain', async () => {
    getContentById.mockResolvedValue({
      id: 'cont-1',
      chunks: [{ id: 'chunk-new', order: 0, text: 'Re-ingested passage' }],
    });

    const result = await instance.run({
      userProfileId: USER_PROFILE_ID,
      id: 'msg-1',
      uniqueContentId: 'cont-1',
      chunkIds: ['chunk-old'],
    });

    expect(result.text).toBe('Hello');
    expect(result).not.toHaveProperty('chunks');
  });

  it('does not load ingested chunks when the params have none', async () => {
    const result = await run();

    expect(getContentById).not.toHaveBeenCalled();
    expect(result.chunks).toBeUndefined();
  });

  it('requests the HTML body when editing a draft', async () => {
    const result = await instance.run({
      userProfileId: USER_PROFILE_ID,
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

  it('reads a message whose attachments Graph returns as null', async () => {
    graphRequest.get.mockResolvedValue({ ...graphMessage, isDraft: true, attachments: null });

    const { metadata } = await run();

    expect(metadata).toMatchObject({ isDraft: true, attachments: [] });
  });

  it('still returns the attachments Graph sent when it marks the list as cut short', async () => {
    graphRequest.get.mockResolvedValue({
      ...graphMessage,
      attachments: [{ name: 'offer.pdf', size: 10, isInline: false }],
      'attachments@odata.nextLink':
        'https://graph.microsoft.com/v1.0/me/messages/msg-1/attachments?$skip=20',
    });

    const { metadata } = await run();

    expect(metadata.attachments).toEqual([{ name: 'offer.pdf', size: 10, isInline: false }]);
  });

  it('marks a message without the draft flag as not a draft', async () => {
    const { metadata } = await run();

    expect(metadata).toMatchObject({ isDraft: false, attachments: [] });
  });
});
