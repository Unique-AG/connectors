import { UniqueQLOperator } from '@unique-ag/unique-api';
import { describe, expect, it } from 'vitest';
import { buildSearchFilter, clampToValidDate } from './search-conditions.dto';

describe('clampToValidDate', () => {
  it('passes through non-string values unchanged', () => {
    expect(clampToValidDate(null)).toBeNull();
    expect(clampToValidDate(42)).toBe(42);
    expect(clampToValidDate(undefined)).toBeUndefined();
  });

  it('passes through strings that do not match ISO datetime format', () => {
    expect(clampToValidDate('not-a-date')).toBe('not-a-date');
    expect(clampToValidDate('2026-02-29')).toBe('2026-02-29');
  });

  it('passes through valid dates unchanged', () => {
    expect(clampToValidDate('2026-02-28T23:59:59Z')).toBe('2026-02-28T23:59:59Z');
    expect(clampToValidDate('2026-01-31T00:00:00Z')).toBe('2026-01-31T00:00:00Z');
    expect(clampToValidDate('2026-03-31T12:00:00Z')).toBe('2026-03-31T12:00:00Z');
  });

  it('clamps Feb 29 to Feb 28 in a non-leap year', () => {
    expect(clampToValidDate('2026-02-29T23:59:59Z')).toBe('2026-02-28T23:59:59Z');
    expect(clampToValidDate('2025-02-29T00:00:00Z')).toBe('2025-02-28T00:00:00Z');
  });

  it('allows Feb 29 in a leap year', () => {
    expect(clampToValidDate('2024-02-29T00:00:00Z')).toBe('2024-02-29T00:00:00Z');
    expect(clampToValidDate('2028-02-29T23:59:59Z')).toBe('2028-02-29T23:59:59Z');
  });

  it('clamps day 31 to day 30 in months with 30 days', () => {
    expect(clampToValidDate('2026-04-31T00:00:00Z')).toBe('2026-04-30T00:00:00Z');
    expect(clampToValidDate('2026-06-31T00:00:00Z')).toBe('2026-06-30T00:00:00Z');
    expect(clampToValidDate('2026-11-31T12:00:00Z')).toBe('2026-11-30T12:00:00Z');
  });
});

describe('buildSearchFilter', () => {
  it('returns undefined when conditions is undefined', () => {
    const result = buildSearchFilter(undefined);

    expect(result).toBeUndefined();
  });

  it('returns undefined when conditions is an empty array', () => {
    const result = buildSearchFilter([]);

    expect(result).toBeUndefined();
  });

  it('builds a scalar filter for dateFrom', () => {
    const result = buildSearchFilter([
      { dateFrom: { value: '2024-01-01', operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL } },
    ]);

    expect(result).toEqual({
      path: ['receivedDateTime'],
      operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL,
      value: '2024-01-01',
    });
  });

  it('builds a scalar filter for dateTo', () => {
    const result = buildSearchFilter([
      { dateTo: { value: '2024-12-31', operator: UniqueQLOperator.LESS_THAN_OR_EQUAL } },
    ]);

    expect(result).toEqual({
      path: ['receivedDateTime'],
      operator: UniqueQLOperator.LESS_THAN_OR_EQUAL,
      value: '2024-12-31',
    });
  });

  it('passes array value as-is for an array field', () => {
    const result = buildSearchFilter([
      { fromSenders: { value: ['alice@example.com'], operator: UniqueQLOperator.IN } },
    ]);

    expect(result).toEqual({
      path: ['fromEmailAddress'],
      operator: UniqueQLOperator.IN,
      value: ['alice@example.com'],
    });
  });

  it('passes multiple array values as-is', () => {
    const result = buildSearchFilter([
      {
        fromSenders: {
          value: ['alice@example.com', 'bob@example.com'],
          operator: UniqueQLOperator.IN,
        },
      },
    ]);

    expect(result).toEqual({
      path: ['fromEmailAddress'],
      operator: UniqueQLOperator.IN,
      value: ['alice@example.com', 'bob@example.com'],
    });
  });

  it('ANDs multiple keys within a single condition group', () => {
    const result = buildSearchFilter([
      {
        dateFrom: { value: '2024-01-01', operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL },
        fromSenders: { value: ['alice@example.com'], operator: UniqueQLOperator.IN },
      },
    ]);

    expect(result).toEqual({
      and: [
        {
          path: ['receivedDateTime'],
          operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL,
          value: '2024-01-01',
        },
        {
          path: ['fromEmailAddress'],
          operator: UniqueQLOperator.IN,
          value: ['alice@example.com'],
        },
      ],
    });
  });

  it('ORs multiple condition groups', () => {
    const result = buildSearchFilter([
      { dateFrom: { value: '2024-01-01', operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL } },
      { directories: { value: ['inbox-id'], operator: UniqueQLOperator.IN } },
    ]);

    expect(result).toEqual({
      or: [
        {
          path: ['receivedDateTime'],
          operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL,
          value: '2024-01-01',
        },
        {
          path: ['parentFolderId'],
          operator: UniqueQLOperator.IN,
          value: ['inbox-id'],
        },
      ],
    });
  });

  it('uses correct metadata paths for toRecipients, ccRecipients, and categories', () => {
    const result = buildSearchFilter([
      {
        toRecipients: { value: ['carol@example.com'], operator: UniqueQLOperator.IN },
        ccRecipients: { value: ['dave@example.com'], operator: UniqueQLOperator.IN },
        categories: { value: ['important'], operator: UniqueQLOperator.IN },
      },
    ]);

    expect(result).toEqual({
      and: [
        {
          path: ['toRecipientsEmailAddresses'],
          operator: UniqueQLOperator.IN,
          value: ['carol@example.com'],
        },
        {
          path: ['ccRecipientsEmailAddresses'],
          operator: UniqueQLOperator.IN,
          value: ['dave@example.com'],
        },
        {
          path: ['categories'],
          operator: UniqueQLOperator.IN,
          value: ['important'],
        },
      ],
    });
  });

  it('passes hasAttachments boolean value as-is', () => {
    const resultTrue = buildSearchFilter([
      { hasAttachments: { value: true, operator: UniqueQLOperator.EQUALS } },
    ]);

    expect(resultTrue).toEqual({
      path: ['hasAttachments'],
      operator: UniqueQLOperator.EQUALS,
      value: true,
    });

    const resultFalse = buildSearchFilter([
      { hasAttachments: { value: false, operator: UniqueQLOperator.EQUALS } },
    ]);

    expect(resultFalse).toEqual({
      path: ['hasAttachments'],
      operator: UniqueQLOperator.EQUALS,
      value: false,
    });
  });
});
