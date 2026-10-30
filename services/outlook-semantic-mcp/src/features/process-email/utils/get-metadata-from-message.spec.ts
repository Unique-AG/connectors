import { describe, expect, it } from 'vitest';
import { GraphMessage, graphMessageSchema } from '../dtos/microsoft-graph.dtos';
import { getMetadataFromMessage } from './get-metadata-from-message';

const baseMessage: GraphMessage = {
  id: 'msg-1',
  createdDateTime: '2026-01-01T00:00:00Z',
  lastModifiedDateTime: '2026-01-01T00:00:00Z',
  receivedDateTime: '2026-01-01T00:00:00Z',
  parentFolderId: 'folder-1',
  webLink: 'https://outlook.test/msg-1',
};

describe('getMetadataFromMessage', () => {
  it('stores every attachment name, and the inline ones separately', () => {
    const metadata = getMetadataFromMessage({
      ...baseMessage,
      hasAttachments: true,
      attachments: [
        { name: 'offer.pdf', isInline: false },
        { name: 'logo.png', isInline: true },
        { name: 'terms.docx' },
      ],
    });

    expect(metadata.attachmentNames).toEqual(['offer.pdf', 'logo.png', 'terms.docx']);
    expect(metadata.inlineAttachmentNames).toEqual(['logo.png']);
  });

  it('accepts an attachment without a name and leaves it out', () => {
    const message = graphMessageSchema.parse({
      ...baseMessage,
      attachments: [
        { name: null, isInline: true },
        { name: 'offer.pdf', isInline: false },
      ],
    });

    const metadata = getMetadataFromMessage(message);

    expect(metadata.attachmentNames).toEqual(['offer.pdf']);
    expect(metadata.inlineAttachmentNames).toEqual([]);
  });

  it('stores no attachment names when Graph returned none', () => {
    expect(getMetadataFromMessage(baseMessage).attachmentNames).toEqual([]);
  });

  it.each([
    [true, 'true'],
    [false, 'false'],
    [undefined, 'false'],
  ])('stores isDraft %s as %s', (isDraft, expected) => {
    expect(getMetadataFromMessage({ ...baseMessage, isDraft }).isDraft).toBe(expected);
  });
});
