import { describe, expect, it } from 'vitest';
import { buildKqlQueryString } from './graph-search-emails.query';

describe('buildKqlQueryString', () => {
  it('returns just the search string when there are no conditions', () => {
    const result = buildKqlQueryString({ search: 'quarterly report', limit: 25 });
    expect(result).toBe('quarterly report');
  });

  it('returns just the search string when conditions array is empty', () => {
    const result = buildKqlQueryString({ search: 'quarterly report', conditions: [], limit: 25 });
    expect(result).toBe('quarterly report');
  });

  it('appends dateFrom predicate with date part only', () => {
    const result = buildKqlQueryString({
      search: 'report',
      conditions: [{ dateFrom: { value: '2024-03-15T00:00:00Z', operator: 'greaterThanOrEqual' } }],
    });
    expect(result).toBe('report AND received>=2024-03-15');
  });

  it('appends dateTo predicate with date part only', () => {
    const result = buildKqlQueryString({
      search: 'report',
      conditions: [{ dateTo: { value: '2024-12-31T23:59:59Z', operator: 'lessThanOrEqual' } }],
    });
    expect(result).toBe('report AND received<=2024-12-31');
  });

  it('appends both dateFrom and dateTo in the same condition', () => {
    const result = buildKqlQueryString({
      search: 'report',
      conditions: [
        {
          dateFrom: { value: '2024-01-01T00:00:00Z', operator: 'greaterThanOrEqual' },
          dateTo: { value: '2024-12-31T23:59:59Z', operator: 'lessThanOrEqual' },
        },
      ],
    });
    expect(result).toBe('report AND received>=2024-01-01 AND received<=2024-12-31');
  });

  it('builds singular equals fromSenders predicate', () => {
    const result = buildKqlQueryString({
      search: 'hello',
      conditions: [{ fromSenders: { value: 'alice@example.com', operator: 'equals' } }],
    });
    expect(result).toBe('hello AND from:alice@example.com');
  });

  it('builds array in fromSenders predicate joined with OR', () => {
    const result = buildKqlQueryString({
      search: 'hello',
      conditions: [
        { fromSenders: { value: ['alice@example.com', 'bob@example.com'], operator: 'in' } },
      ],
    });
    expect(result).toBe('hello AND (from:alice@example.com OR from:bob@example.com)');
  });

  it('builds containsAny fromSenders predicate joined with OR', () => {
    const result = buildKqlQueryString({
      search: 'hello',
      conditions: [
        {
          fromSenders: { value: ['google.com', 'microsoft.com'], operator: 'containsAny' },
        },
      ],
    });
    expect(result).toBe('hello AND (from:google.com OR from:microsoft.com)');
  });

  it('skips notIn fromSenders silently', () => {
    const result = buildKqlQueryString({
      search: 'hello',
      conditions: [{ fromSenders: { value: ['alice@example.com'], operator: 'notIn' } }],
    });
    expect(result).toBe('hello');
  });

  it('builds singular toRecipients predicate', () => {
    const result = buildKqlQueryString({
      search: 'meeting',
      conditions: [{ toRecipients: { value: 'bob@example.com', operator: 'equals' } }],
    });
    expect(result).toBe('meeting AND to:bob@example.com');
  });

  it('builds array in toRecipients predicate joined with OR', () => {
    const result = buildKqlQueryString({
      search: 'meeting',
      conditions: [
        { toRecipients: { value: ['bob@example.com', 'carol@example.com'], operator: 'in' } },
      ],
    });
    expect(result).toBe('meeting AND (to:bob@example.com OR to:carol@example.com)');
  });

  it('skips notIn toRecipients silently', () => {
    const result = buildKqlQueryString({
      search: 'meeting',
      conditions: [{ toRecipients: { value: ['bob@example.com'], operator: 'notIn' } }],
    });
    expect(result).toBe('meeting');
  });

  it('builds singular ccRecipients predicate', () => {
    const result = buildKqlQueryString({
      search: 'update',
      conditions: [{ ccRecipients: { value: 'carol@example.com', operator: 'equals' } }],
    });
    expect(result).toBe('update AND cc:carol@example.com');
  });

  it('builds array in ccRecipients predicate joined with OR', () => {
    const result = buildKqlQueryString({
      search: 'update',
      conditions: [
        { ccRecipients: { value: ['carol@example.com', 'dave@example.com'], operator: 'in' } },
      ],
    });
    expect(result).toBe('update AND (cc:carol@example.com OR cc:dave@example.com)');
  });

  it('skips notIn ccRecipients silently', () => {
    const result = buildKqlQueryString({
      search: 'update',
      conditions: [{ ccRecipients: { value: ['carol@example.com'], operator: 'notIn' } }],
    });
    expect(result).toBe('update');
  });

  it('builds hasAttachments:true predicate', () => {
    const result = buildKqlQueryString({
      search: 'invoice',
      conditions: [{ hasAttachments: { value: 'true', operator: 'equals' } }],
    });
    expect(result).toBe('invoice AND hasAttachment:true');
  });

  it('builds hasAttachments:false predicate', () => {
    const result = buildKqlQueryString({
      search: 'note',
      conditions: [{ hasAttachments: { value: 'false', operator: 'equals' } }],
    });
    expect(result).toBe('note AND hasAttachment:false');
  });

  it('builds singular categories predicate with quotes', () => {
    const result = buildKqlQueryString({
      search: 'tasks',
      conditions: [{ categories: { value: 'Important', operator: 'equals' } }],
    });
    expect(result).toBe('tasks AND category:"Important"');
  });

  it('builds array in categories predicate joined with OR', () => {
    const result = buildKqlQueryString({
      search: 'tasks',
      conditions: [{ categories: { value: ['Important', 'Project-X'], operator: 'in' } }],
    });
    expect(result).toBe('tasks AND (category:"Important" OR category:"Project-X")');
  });

  it('skips notIn categories silently', () => {
    const result = buildKqlQueryString({
      search: 'tasks',
      conditions: [{ categories: { value: ['Important'], operator: 'notIn' } }],
    });
    expect(result).toBe('tasks');
  });

  it('skips directories silently', () => {
    const result = buildKqlQueryString({
      search: 'invoice',
      conditions: [{ directories: { value: ['inbox-id-123'], operator: 'in' } }],
    });
    expect(result).toBe('invoice');
  });

  it('joins multiple fields within one condition with AND', () => {
    const result = buildKqlQueryString({
      search: 'report',
      conditions: [
        {
          fromSenders: { value: 'alice@example.com', operator: 'equals' },
          hasAttachments: { value: 'true', operator: 'equals' },
        },
      ],
    });
    expect(result).toBe('report AND from:alice@example.com AND hasAttachment:true');
  });

  it('joins multiple condition objects with AND', () => {
    const result = buildKqlQueryString({
      search: 'report',
      conditions: [
        { fromSenders: { value: 'alice@example.com', operator: 'equals' } },
        { toRecipients: { value: 'bob@example.com', operator: 'equals' } },
      ],
    });
    expect(result).toBe('report AND from:alice@example.com AND to:bob@example.com');
  });

  it('handles a condition object where all fields are unsupported (notIn) and produces just search', () => {
    const result = buildKqlQueryString({
      search: 'anything',
      conditions: [
        {
          fromSenders: { value: ['alice@example.com'], operator: 'notIn' },
          directories: { value: ['inbox-id-123'], operator: 'in' },
        },
      ],
    });
    expect(result).toBe('anything');
  });

  it('parenthesises OR group when combined with another AND condition', () => {
    const result = buildKqlQueryString({
      search: 'report',
      conditions: [
        {
          fromSenders: { value: ['alice@example.com', 'bob@example.com'], operator: 'in' },
          hasAttachments: { value: 'true', operator: 'equals' },
        },
      ],
    });
    expect(result).toBe(
      'report AND (from:alice@example.com OR from:bob@example.com) AND hasAttachment:true',
    );
  });
});
