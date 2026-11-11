import { describe, expect, it } from 'vitest';
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
