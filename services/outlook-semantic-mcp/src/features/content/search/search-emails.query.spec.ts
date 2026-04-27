import { describe, expect, it } from 'vitest';
import { SearchBackend, SearchEmailResult } from './semantic-search-emails.query';
import { SearchEmailsQuery } from './search-emails.query';

function makeGraphResult(emailId: string, overrides?: Partial<SearchEmailResult>): SearchEmailResult {
  return {
    id: emailId,
    emailId,
    folderId: 'folder-1',
    title: 'Graph Email',
    from: 'sender@example.com',
    outlookWebLink: 'https://outlook.com/msg/1',
    receivedDateTime: '2024-01-01T00:00:00Z',
    text: 'Graph body',
    url: undefined,
    backend: SearchBackend.MsGraph,
    ...overrides,
  };
}

function makeUniqueResult(emailId: string, overrides?: Partial<SearchEmailResult>): SearchEmailResult {
  return {
    id: emailId,
    emailId,
    folderId: 'folder-2',
    title: 'Unique Email',
    from: 'sender@example.com',
    outlookWebLink: 'https://outlook.com/msg/2',
    receivedDateTime: '2024-01-01T00:00:00Z',
    text: 'Unique body',
    url: 'https://unique.example.com/doc/1',
    backend: SearchBackend.Unique,
    ...overrides,
  };
}

// biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
const mergeResults = (instance: SearchEmailsQuery, resultSets: SearchEmailResult[][]): SearchEmailResult[] =>
  (instance as any).mergeResults(resultSets);

describe('SearchEmailsQuery.mergeResults', () => {
  const instance = new SearchEmailsQuery(
    // biome-ignore lint/suspicious/noExplicitAny: test stub
    null as any,
    // biome-ignore lint/suspicious/noExplicitAny: test stub
    null as any,
  );

  it('returns graph-only results unmodified', () => {
    const graphA = makeGraphResult('email-1');
    const graphB = makeGraphResult('email-2');

    const result = mergeResults(instance, [[graphA, graphB]]);

    expect(result).toEqual([graphA, graphB]);
  });

  it('returns unique-only results unmodified', () => {
    const uniqueA = makeUniqueResult('email-1');
    const uniqueB = makeUniqueResult('email-2');

    const result = mergeResults(instance, [[uniqueA], [uniqueB]]);

    expect(result).toEqual([uniqueA, uniqueB]);
  });

  it('drops unique duplicate when emailId overlaps with a graph result', () => {
    const graphResult = makeGraphResult('email-shared');
    const uniqueDuplicate = makeUniqueResult('email-shared');

    const result = mergeResults(instance, [[graphResult], [uniqueDuplicate]]);

    expect(result).toHaveLength(1);
    expect(result[0]).toEqual(graphResult);
  });

  it('places graph results first and appends unique-only results after', () => {
    const graphA = makeGraphResult('email-graph-only');
    const graphShared = makeGraphResult('email-shared');
    const uniqueShared = makeUniqueResult('email-shared');
    const uniqueOnly = makeUniqueResult('email-unique-only');

    const result = mergeResults(instance, [[graphA, graphShared], [uniqueShared, uniqueOnly]]);

    expect(result).toHaveLength(3);
    expect(result[0]).toEqual(graphA);
    expect(result[1]).toEqual(graphShared);
    expect(result[2]).toEqual(uniqueOnly);
  });

  it('returns empty array when all result sets are empty', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (instance as any).mergeResults([[], []]);
    expect(result).toEqual([]);
  });
});
