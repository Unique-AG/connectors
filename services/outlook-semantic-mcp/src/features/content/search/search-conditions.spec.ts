import { UniqueQLOperator } from '@unique-ag/unique-api';
import { describe, expect, it } from 'vitest';
import { buildSearchFilter, CONTAINS_ANY_OPERATOR } from './search-conditions.dto';

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

  it('expands containsAny with multiple emails to an or of contains leaves', () => {
    const result = buildSearchFilter([
      {
        fromSenders: {
          value: ['alice@example.com', 'bob@example.com'],
          operator: CONTAINS_ANY_OPERATOR,
        },
      },
    ]);

    expect(result).toEqual({
      or: [
        {
          path: ['fromEmailAddress'],
          operator: UniqueQLOperator.CONTAINS,
          value: 'alice@example.com',
        },
        {
          path: ['fromEmailAddress'],
          operator: UniqueQLOperator.CONTAINS,
          value: 'bob@example.com',
        },
      ],
    });
  });

  it('unwraps containsAny with a single value to a bare contains leaf', () => {
    const result = buildSearchFilter([
      {
        fromSenders: {
          value: ['alice@example.com'],
          operator: CONTAINS_ANY_OPERATOR,
        },
      },
    ]);

    expect(result).toEqual({
      path: ['fromEmailAddress'],
      operator: UniqueQLOperator.CONTAINS,
      value: 'alice@example.com',
    });
  });

  it('ANDs containsAny with other conditions in the same group', () => {
    const result = buildSearchFilter([
      {
        dateFrom: { value: '2024-01-01', operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL },
        fromSenders: {
          value: ['alice@example.com', 'bob@example.com'],
          operator: CONTAINS_ANY_OPERATOR,
        },
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
          or: [
            {
              path: ['fromEmailAddress'],
              operator: UniqueQLOperator.CONTAINS,
              value: 'alice@example.com',
            },
            {
              path: ['fromEmailAddress'],
              operator: UniqueQLOperator.CONTAINS,
              value: 'bob@example.com',
            },
          ],
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
