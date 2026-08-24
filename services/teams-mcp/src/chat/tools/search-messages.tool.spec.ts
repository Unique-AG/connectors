import { describe, expect, it } from 'vitest';
import { SearchMessagesInputSchema } from './search-messages.tool';

describe('SearchMessagesInputSchema', () => {
  // Graph's search projection carries no message body, only a clipped `summary`
  // snippet, so a summary-only default sends the caller straight to
  // get_chat_messages for the same hits it just returned (UN-24234).
  it('defaults detail to full so hits carry message bodies', () => {
    const result = SearchMessagesInputSchema.parse({ query: 'release' });

    expect(result.detail).toBe('full');
  });

  it('honours an explicit summary detail', () => {
    const result = SearchMessagesInputSchema.parse({ query: 'release', detail: 'summary' });

    expect(result.detail).toBe('summary');
  });

  it('applies the remaining defaults', () => {
    const result = SearchMessagesInputSchema.parse({ query: 'release' });

    expect(result.source).toBe('all');
    expect(result.contentFormat).toBe('normalized');
    expect(result.offset).toBe(0);
    expect(result.size).toBe(25);
  });

  it('rejects a search with no criterion', () => {
    expect(() => SearchMessagesInputSchema.parse({})).toThrow();
  });
});
