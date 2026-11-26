import { afterEach, describe, expect, it, vi } from 'vitest';
import * as z from 'zod';
import { ExistingDraftTargetShape } from '../draft-input.schemas';

const schema = z.object(ExistingDraftTargetShape);

describe('ExistingDraftTargetShape', () => {
  it('accepts the target a search result carries', () => {
    const target = {
      draftId: 'AQMk/ADRh+immutable_id=',
      idIsImmutable: true,
      mailbox: 'shared@example.com',
      parentFolderId: 'AQMk/folder-1=',
    };

    expect(schema.parse(target)).toEqual(target);
  });

  it('accepts a draft in the own mailbox with only its id', () => {
    expect(schema.parse({ draftId: 'draft-1' })).toEqual({ draftId: 'draft-1' });
  });

  it.each([
    ['a query string in draftId', { draftId: 'abc?$select=body' }],
    ['a fragment in draftId', { draftId: 'abc#frag' }],
    ['a percent escape in draftId', { draftId: 'abc%2e%2e' }],
    ['an empty draftId', { draftId: '' }],
    ['a path in mailbox', { draftId: 'draft-1', mailbox: 'me/messages/abc' }],
    ['a query string after a mailbox', { draftId: 'draft-1', mailbox: 'a@b.com?x=1' }],
    ['a path in parentFolderId', { draftId: 'draft-1', parentFolderId: '../inbox' }],
  ])('rejects %s', (_name, target) => {
    expect(schema.safeParse(target).success).toBe(false);
  });
});

describe('DraftAttachmentsSchema', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  const dataDescriptionWith = async (uniqueAttachments: 'enabled' | 'disabled') => {
    vi.stubEnv('UNIQUE_ATTACHMENTS', uniqueAttachments);
    vi.resetModules();
    const { DraftAttachmentsSchema } = await import('../draft-input.schemas');
    return DraftAttachmentsSchema.element.shape.data.description;
  };

  it('offers unique:// files when Unique attachments are on', async () => {
    expect(await dataDescriptionWith('enabled')).toContain('unique://content/{contentId}');
  });

  it('offers only data: URIs when Unique attachments are off', async () => {
    const description = await dataDescriptionWith('disabled');

    expect(description).not.toContain('unique://');
    expect(description).toContain('data:[mediatype];base64,<base64data>');
  });
});
