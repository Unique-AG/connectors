import { describe, expect, it } from 'vitest';
import { SearchEmailsQuery } from './search-emails.query';

// biome-ignore lint/suspicious/noExplicitAny: constructor args not needed for this private method
const query = new SearchEmailsQuery(null as any, null as any);

type MockDirectory = {
  providerDirectoryId: string;
  displayName: string;
};

const inboxDir: MockDirectory = { providerDirectoryId: 'inbox-id-123', displayName: 'Inbox' };
const sentDir: MockDirectory = { providerDirectoryId: 'sent-id-456', displayName: 'Sent Items' };

describe('SearchEmailsQuery.sanitizeWrongDirectoryIds', () => {
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
