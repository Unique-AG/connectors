import { describe, expect, it } from 'vitest';
import { buildSearchQuery } from './build-search-query';

describe('buildSearchQuery', () => {
  it('returns an empty string when no parameters are set', () => {
    expect(buildSearchQuery({})).toBe('');
  });

  it('emits single-word free text unquoted', () => {
    expect(buildSearchQuery({ query: 'budget' })).toBe('budget');
  });

  it('quotes multi-word free text', () => {
    expect(buildSearchQuery({ query: 'quarterly budget' })).toBe('"quarterly budget"');
  });

  it('emits a single-token from value unquoted', () => {
    expect(buildSearchQuery({ from: 'alice@contoso.com' })).toBe('from:alice@contoso.com');
  });

  it('quotes a from value that contains whitespace', () => {
    expect(buildSearchQuery({ from: 'Alice Smith' })).toBe('from:"Alice Smith"');
  });

  it('guards against KQL injection by quoting operator-bearing values', () => {
    // Without quoting this would smuggle a `sent>` operator into the query.
    expect(buildSearchQuery({ from: 'Bob sent>2020-01-01' })).toBe('from:"Bob sent>2020-01-01"');
  });

  it('escapes embedded double quotes by doubling them', () => {
    expect(buildSearchQuery({ from: 'O"Brien' })).toBe('from:"O""Brien"');
  });

  it('strips dashes from a mentions GUID', () => {
    expect(buildSearchQuery({ mentions: '11112222-3333-4444-5555-666677778888' })).toBe(
      'mentions:11112222333344445555666677778888',
    );
  });

  it('slices sentAfter to a date and uses the > operator', () => {
    expect(buildSearchQuery({ sentAfter: '2024-01-15T10:30:00.000Z' })).toBe('sent>2024-01-15');
  });

  it('slices sentBefore to a date and uses the < operator', () => {
    expect(buildSearchQuery({ sentBefore: '2024-01-31T23:59:59.999Z' })).toBe('sent<2024-01-31');
  });

  it('emits hasAttachment with exact KQL casing', () => {
    expect(buildSearchQuery({ hasAttachment: true })).toBe('hasAttachment:true');
  });

  it('emits boolean restrictions when false (not just true)', () => {
    expect(buildSearchQuery({ isRead: false })).toBe('IsRead:false');
    expect(buildSearchQuery({ isMentioned: false })).toBe('IsMentioned:false');
  });

  it('omits boolean restrictions that are undefined', () => {
    expect(buildSearchQuery({ query: 'hi' })).toBe('hi');
  });

  it('orders free text first, then property restrictions', () => {
    const result = buildSearchQuery({
      query: 'report',
      from: 'alice@contoso.com',
      to: 'bob@contoso.com',
      mentions: 'aaaa-bbbb',
      sentAfter: '2024-01-01',
      sentBefore: '2024-12-31',
      hasAttachment: true,
      isRead: false,
      isMentioned: true,
    });

    expect(result).toBe(
      'report from:alice@contoso.com to:bob@contoso.com mentions:aaaabbbb sent>2024-01-01 sent<2024-12-31 hasAttachment:true IsRead:false IsMentioned:true',
    );
  });
});
