import { describe, expect, it } from 'vitest';
import { filterConditionsForMailbox } from '../filter-conditions-for-mailbox';
import { SanitizeSearchConditionsForUserQuery } from '../sanitize-search-conditions-for-user.query';
import { SearchConditionSchema } from '../semantic-search-conditions.dto';

describe('SearchConditionSchema', () => {
  it('accepts a valid mailbox email alongside another filter field', () => {
    const result = SearchConditionSchema.safeParse({
      mailbox: 'alice@example.com',
      hasAttachments: { value: 'true', operator: 'equals' },
    });

    expect(result.success).toBe(true);
  });

  it('rejects a non-email value for mailbox', () => {
    const result = SearchConditionSchema.safeParse({
      mailbox: 'not-an-email',
      hasAttachments: { value: 'true', operator: 'equals' },
    });

    expect(result.success).toBe(false);
  });

  it('accepts a condition without mailbox (existing behavior)', () => {
    const result = SearchConditionSchema.safeParse({
      hasAttachments: { value: 'false', operator: 'equals' },
    });

    expect(result.success).toBe(true);
  });

  it('fails the refine when mailbox is the only field provided', () => {
    const result = SearchConditionSchema.safeParse({
      mailbox: 'alice@example.com',
    });

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toMatch(/Invalid search condition/);
    }
  });
});

// biome-ignore lint/suspicious/noExplicitAny: constructor args not needed for this private method
const query = new SanitizeSearchConditionsForUserQuery(null as any);

interface MockDirectory {
  providerDirectoryId: string;
  displayName: string;
}

const inboxDir: MockDirectory = { providerDirectoryId: 'inbox-id-123', displayName: 'Inbox' };
const sentDir: MockDirectory = { providerDirectoryId: 'sent-id-456', displayName: 'Sent Items' };

describe('SanitizeSearchConditionsForUserQuery.sanitizeWrongDirectoryIds', () => {
  it('returns the ID unchanged when it exactly matches a providerDirectoryId', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['inbox-id-123'], [inboxDir]);

    expect(result).toEqual({ resolvedIds: ['inbox-id-123'], unrecognized: [] });
  });

  it('resolves a display name fuzzy match above threshold to the correct providerDirectoryId', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['inbox'], [inboxDir]);

    expect(result).toEqual({ resolvedIds: ['inbox-id-123'], unrecognized: [] });
  });

  it('places a string below the similarity threshold into unrecognized', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['xyz123'], [inboxDir]);

    expect(result).toEqual({ resolvedIds: [], unrecognized: ['xyz123'] });
  });

  it('resolves a string at exactly the 80% similarity threshold', () => {
    // "Inboc" vs "Inbox": distance 1, max length 5 → similarity 0.8 (at threshold, should match)
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['Inboc'], [inboxDir]);

    expect(result).toEqual({ resolvedIds: ['inbox-id-123'], unrecognized: [] });
  });

  it('rejects a string just below the 80% similarity threshold', () => {
    // "Inbcc" vs "Inbox": distance 2, max length 5 → similarity 0.6 (below threshold)
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['Inbcc'], [inboxDir]);

    expect(result).toEqual({ resolvedIds: [], unrecognized: ['Inbcc'] });
  });

  it('splits mixed input correctly between resolvedIds and unrecognized', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(
      ['inbox-id-123', 'xyz123'],
      [inboxDir, sentDir],
    );

    expect(result).toEqual({ resolvedIds: ['inbox-id-123'], unrecognized: ['xyz123'] });
  });

  it('places all inputs into unrecognized when none match any directory', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['foo', 'bar'], [inboxDir, sentDir]);

    expect(result).toEqual({ resolvedIds: [], unrecognized: ['foo', 'bar'] });
  });
});

const attachment = { value: 'true' as const, operator: 'equals' as const };

describe('filterConditionsForMailbox', () => {
  it('keeps a matching-mailbox condition and strips the mailbox key', () => {
    const result = filterConditionsForMailbox(
      [{ mailbox: 'alice@example.com', hasAttachments: attachment }],
      'alice@example.com',
    );

    expect(result).toEqual([{ hasAttachments: attachment }]);
    expect(result[0]).not.toHaveProperty('mailbox');
  });

  it('drops a condition whose mailbox does not match the branch email', () => {
    const result = filterConditionsForMailbox(
      [{ mailbox: 'bob@example.com', hasAttachments: attachment }],
      'alice@example.com',
    );

    expect(result).toEqual([]);
  });

  it('keeps a condition that has no mailbox field', () => {
    const result = filterConditionsForMailbox(
      [{ hasAttachments: attachment }],
      'alice@example.com',
    );

    expect(result).toEqual([{ hasAttachments: attachment }]);
    expect(result[0]).not.toHaveProperty('mailbox');
  });

  it('returns the correct subset for a mixed list', () => {
    const aliceAttachment = { value: 'true' as const, operator: 'equals' as const };
    const globalAttachment = { value: 'false' as const, operator: 'equals' as const };

    const result = filterConditionsForMailbox(
      [
        { mailbox: 'alice@example.com', hasAttachments: aliceAttachment },
        { mailbox: 'bob@example.com', hasAttachments: attachment },
        { hasAttachments: globalAttachment },
      ],
      'alice@example.com',
    );

    expect(result).toEqual([
      { hasAttachments: aliceAttachment },
      { hasAttachments: globalAttachment },
    ]);
  });

  it('returns [] for an empty list', () => {
    expect(filterConditionsForMailbox([], 'alice@example.com')).toEqual([]);
  });

  it('returns [] when all conditions are filtered out', () => {
    const result = filterConditionsForMailbox(
      [
        { mailbox: 'bob@example.com', hasAttachments: attachment },
        { mailbox: 'carol@example.com', hasAttachments: attachment },
      ],
      'alice@example.com',
    );

    expect(result).toEqual([]);
  });

  it('returns [] for undefined input', () => {
    expect(filterConditionsForMailbox(undefined, 'alice@example.com')).toEqual([]);
  });
});
