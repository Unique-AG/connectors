import { UniqueQLOperator } from '@unique-ag/unique-api';
import { describe, expect, it } from 'vitest';
import { buildSearchFilter } from './search-conditions.dto';

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

  it('uses the leaf directly for an array field with a single value (no or wrapper)', () => {
    const result = buildSearchFilter([
      { fromSenders: { value: ['alice@example.com'], operator: UniqueQLOperator.EQUALS } },
    ]);

    expect(result).toEqual({
      path: ['from.emailAddress'],
      operator: UniqueQLOperator.EQUALS,
      value: 'alice@example.com',
    });
  });

  it('wraps multiple array values in or', () => {
    const result = buildSearchFilter([
      {
        fromSenders: {
          value: ['alice@example.com', 'bob@example.com'],
          operator: UniqueQLOperator.EQUALS,
        },
      },
    ]);

    expect(result).toEqual({
      or: [
        {
          path: ['from.emailAddress'],
          operator: UniqueQLOperator.EQUALS,
          value: 'alice@example.com',
        },
        {
          path: ['from.emailAddress'],
          operator: UniqueQLOperator.EQUALS,
          value: 'bob@example.com',
        },
      ],
    });
  });

  it('ORs multiple keys within a single condition group', () => {
    const result = buildSearchFilter([
      {
        dateFrom: { value: '2024-01-01', operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL },
        fromSenders: { value: ['alice@example.com'], operator: UniqueQLOperator.EQUALS },
      },
    ]);

    expect(result).toEqual({
      or: [
        {
          path: ['receivedDateTime'],
          operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL,
          value: '2024-01-01',
        },
        {
          path: ['from.emailAddress'],
          operator: UniqueQLOperator.EQUALS,
          value: 'alice@example.com',
        },
      ],
    });
  });

  it('ANDs multiple condition groups', () => {
    const result = buildSearchFilter([
      { dateFrom: { value: '2024-01-01', operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL } },
      { directories: { value: ['inbox-id'], operator: UniqueQLOperator.EQUALS } },
    ]);

    expect(result).toEqual({
      and: [
        {
          path: ['receivedDateTime'],
          operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL,
          value: '2024-01-01',
        },
        {
          path: ['parentFolderId'],
          operator: UniqueQLOperator.EQUALS,
          value: 'inbox-id',
        },
      ],
    });
  });

  it('uses correct metadata paths for toRecipients, ccRecipients, and categories', () => {
    const result = buildSearchFilter([
      {
        toRecipients: { value: ['carol@example.com'], operator: UniqueQLOperator.EQUALS },
        ccRecipients: { value: ['dave@example.com'], operator: UniqueQLOperator.EQUALS },
        categories: { value: ['important'], operator: UniqueQLOperator.EQUALS },
      },
    ]);

    expect(result).toEqual({
      or: [
        {
          path: ['toRecipients.emailAddresses'],
          operator: UniqueQLOperator.EQUALS,
          value: 'carol@example.com',
        },
        {
          path: ['ccRecipients.emailAddresses'],
          operator: UniqueQLOperator.EQUALS,
          value: 'dave@example.com',
        },
        {
          path: ['categories'],
          operator: UniqueQLOperator.EQUALS,
          value: 'important',
        },
      ],
    });
  });

  it('converts hasAttachments boolean value to string', () => {
    const resultTrue = buildSearchFilter([
      { hasAttachments: { value: true, operator: UniqueQLOperator.EQUALS } },
    ]);

    expect(resultTrue).toEqual({
      path: ['hasAttachments'],
      operator: UniqueQLOperator.EQUALS,
      value: 'true',
    });

    const resultFalse = buildSearchFilter([
      { hasAttachments: { value: false, operator: UniqueQLOperator.EQUALS } },
    ]);

    expect(resultFalse).toEqual({
      path: ['hasAttachments'],
      operator: UniqueQLOperator.EQUALS,
      value: 'false',
    });
  });
});
