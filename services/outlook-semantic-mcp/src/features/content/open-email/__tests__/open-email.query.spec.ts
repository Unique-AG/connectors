import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { SearchBackend } from '../../search/search-results.types';
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
  let getContentById: Mock;
  let instance: OpenEmailQuery;

  beforeEach(() => {
    graphRequest = {
      header: vi.fn().mockReturnThis(),
      select: vi.fn().mockReturnThis(),
      expand: vi.fn().mockReturnThis(),
      get: vi.fn().mockResolvedValue(graphMessage),
    };
    getContentById = vi.fn();
    instance = new OpenEmailQuery(
      {
        createClientForUser: vi
          .fn()
          .mockReturnValue({ api: vi.fn().mockReturnValue(graphRequest) }),
      } as never,
      { content: { getContentById } } as never,
    );
  });

  describe('Microsoft Graph backend', () => {
    const run = () =>
      instance.run({ userProfileId: 'user-1', id: 'msg-1', idType: SearchBackend.MsGraph });

    it('selects the draft flag and expands the attachment names', async () => {
      await run();

      expect(graphRequest.select).toHaveBeenCalledWith(expect.stringContaining('isDraft'));
      expect(graphRequest.expand).toHaveBeenCalledWith('attachments($select=name,size,isInline)');
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

  describe('Unique backend', () => {
    it.each([
      ['true', true],
      ['false', false],
    ])('exposes stored metadata isDraft %s as %s', async (stored, expected) => {
      getContentById.mockResolvedValue({
        id: 'cont-1',
        title: 'Offer',
        metadata: { isDraft: stored },
        chunks: [],
      });

      const { metadata } = await instance.run({
        userProfileId: 'user-1',
        id: 'cont-1',
        idType: SearchBackend.Unique,
      });

      expect(metadata.isDraft).toBe(expected);
    });

    it('exposes the attachment names stored at ingestion', async () => {
      getContentById.mockResolvedValue({
        id: 'cont-1',
        title: 'Offer',
        metadata: {
          isDraft: 'true',
          attachmentNames: ['offer.pdf', 'logo.png'],
          inlineAttachmentNames: ['logo.png'],
        },
        chunks: [],
      });

      const { metadata } = await instance.run({
        userProfileId: 'user-1',
        id: 'cont-1',
        idType: SearchBackend.Unique,
      });

      expect(metadata.attachments).toEqual([
        { name: 'offer.pdf', isInline: false },
        { name: 'logo.png', isInline: true },
      ]);
    });

    it('returns no attachments for an email ingested without attachment names', async () => {
      getContentById.mockResolvedValue({ id: 'cont-1', title: 'Old', metadata: {}, chunks: [] });

      const { metadata } = await instance.run({
        userProfileId: 'user-1',
        id: 'cont-1',
        idType: SearchBackend.Unique,
      });

      expect(metadata.attachments).toEqual([]);
    });
  });
});
