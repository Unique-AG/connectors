import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  convertUserProfileIdToTypeId,
  type UserProfileTypeID,
} from '~/utils/convert-user-profile-id-to-type-id';
import type { MsGraphKqlSearchEmailsQuery } from '../ms-graph-kql-search-emails.query';
import { SearchEmailsQuery } from '../search-emails.query';
import {
  SearchBackend,
  SearchEmailResult,
  SemanticSearchEmailsQuery,
} from '../semantic-search-emails.query';

const testUserId: UserProfileTypeID = convertUserProfileIdToTypeId(
  `user_profile_01kqcg8m7teh6sh8tehd2k0byb`,
);
function makeGraphResult(
  emailId: string,
  overrides?: Partial<SearchEmailResult>,
): SearchEmailResult {
  return {
    msGraphMessageId: emailId,
    folderId: 'folder-1',
    title: 'Graph Email',
    from: 'sender@example.com',
    outlookWebLink: 'https://outlook.com/msg/1',
    receivedDateTime: '2024-01-01T00:00:00Z',
    text: 'Graph body',
    uniqueContentUrl: undefined,
    backend: SearchBackend.MsGraph,
    ...overrides,
  };
}

function makeUniqueResult(
  emailId: string,
  overrides?: Partial<SearchEmailResult>,
): SearchEmailResult {
  return {
    uniqueContentId: `content-${emailId}`,
    msGraphMessageId: emailId,
    folderId: 'folder-2',
    title: 'Unique Email',
    from: 'sender@example.com',
    outlookWebLink: 'https://outlook.com/msg/2',
    receivedDateTime: '2024-01-01T00:00:00Z',
    text: 'Unique body',
    uniqueContentUrl: 'https://unique.example.com/doc/1',
    backend: SearchBackend.Unique,
    ...overrides,
  };
}

describe('SearchEmailsQuery', () => {
  let semanticSearchQuery: { run: ReturnType<typeof vi.fn> };
  let msGraphKqlQuery: { run: ReturnType<typeof vi.fn> };
  let instance: SearchEmailsQuery;

  beforeEach(() => {
    semanticSearchQuery = { run: vi.fn() };
    msGraphKqlQuery = { run: vi.fn() };
    instance = new SearchEmailsQuery(
      semanticSearchQuery as unknown as SemanticSearchEmailsQuery,
      msGraphKqlQuery as unknown as MsGraphKqlSearchEmailsQuery,
    );
  });

  it('returns only graph results when semanticSearchParams is absent', async () => {
    const graphA = makeGraphResult('email-1');
    const graphB = makeGraphResult('email-2');
    msGraphKqlQuery.run.mockResolvedValue([graphA, graphB]);

    const result = await instance.run(testUserId, {
      msGraphSearchParams: { queries: [{ kqlQuery: 'subject:test' }] },
    });

    expect(result).toHaveLength(2);
    expect(result[0]?.msGraphMessageId).toBe('email-1');
    expect(result[1]?.msGraphMessageId).toBe('email-2');
    expect(semanticSearchQuery.run).not.toHaveBeenCalled();
  });

  it('returns empty array when msGraphSearchParams is absent', async () => {
    const result = await instance.run(testUserId, {});

    expect(result).toEqual([]);
    expect(msGraphKqlQuery.run).not.toHaveBeenCalled();
    expect(semanticSearchQuery.run).not.toHaveBeenCalled();
  });

  it('returns empty array when both backends return no results', async () => {
    semanticSearchQuery.run.mockResolvedValue({ results: [] });
    msGraphKqlQuery.run.mockResolvedValue([]);

    const result = await instance.run(testUserId, {
      semanticSearchParams: { search: 'test', conditions: [], limit: 10 },
      msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
    });

    expect(result).toEqual([]);
  });

  it('places top-20 semantic results first, common remainder second, semantic-only third, graph-only last', async () => {
    // 22 semantic results: indices 0-19 overlap with graph, index 20 has no graph match (semanticOnly), index 21 overlaps with graph (commonRemainder)
    const semanticResults = Array.from({ length: 22 }, (_, i) =>
      makeUniqueResult(`email-${i}`, { text: `Unique body ${i}` }),
    );

    // Graph matches for indices 0-19 and 21 (not 20)
    const graphMatches = Array.from({ length: 20 }, (_, i) =>
      makeGraphResult(`email-${i}`, { text: `Graph body ${i}` }),
    );
    graphMatches.push(makeGraphResult('email-21', { text: 'Graph body 21' }));

    // One graph-only result
    const graphOnly = makeGraphResult('email-graph-only');

    semanticSearchQuery.run.mockResolvedValue({ results: semanticResults });
    msGraphKqlQuery.run.mockResolvedValue([...graphMatches, graphOnly]);

    const result = await instance.run(testUserId, {
      semanticSearchParams: { search: 'test', conditions: [], limit: 25 },
      msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
    });

    expect(result).toHaveLength(23);
    // top20: indices 0-19 (enriched, hadGraphMatch)
    expect(result[0]?.msGraphMessageId).toBe('email-0');
    expect(result[19]?.msGraphMessageId).toBe('email-19');
    // commonRemainder: index 21 (hadGraphMatch, beyond top20)
    expect(result[20]?.msGraphMessageId).toBe('email-21');
    // semanticOnly: index 20 (no graph match, beyond top20)
    expect(result[21]?.msGraphMessageId).toBe('email-20');
    // remainingGraph: graph-only
    expect(result[22]?.msGraphMessageId).toBe('email-graph-only');
  });

  it('semantic-only results beyond top-20 appear before graph-only results', async () => {
    // 21 semantic results, none overlap with graph
    const semanticResults = Array.from({ length: 21 }, (_, i) =>
      makeUniqueResult(`email-semantic-${i}`),
    );
    const graphOnly = makeGraphResult('email-graph-only');

    semanticSearchQuery.run.mockResolvedValue({ results: semanticResults });
    msGraphKqlQuery.run.mockResolvedValue([graphOnly]);

    const result = await instance.run(testUserId, {
      semanticSearchParams: { search: 'test', conditions: [], limit: 25 },
      msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
    });

    expect(result).toHaveLength(22);
    // top20: indices 0-19
    expect(result[0]?.msGraphMessageId).toBe('email-semantic-0');
    expect(result[19]?.msGraphMessageId).toBe('email-semantic-19');
    // semanticOnly remainder: index 20
    expect(result[20]?.msGraphMessageId).toBe('email-semantic-20');
    // graph-only last
    expect(result[21]?.msGraphMessageId).toBe('email-graph-only');
  });

  it('enriches text with both sections when email matched by both backends', async () => {
    const semanticResult = makeUniqueResult('email-1', { text: 'Semantic content' });
    const graphResult = makeGraphResult('email-1', { text: 'Graph content' });

    semanticSearchQuery.run.mockResolvedValue({ results: [semanticResult] });
    msGraphKqlQuery.run.mockResolvedValue([graphResult]);

    const result = await instance.run(testUserId, {
      semanticSearchParams: { search: 'test', conditions: [], limit: 10 },
      msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
    });

    expect(result[0]?.text).toBe(
      '## Semantically Matched Content\nSemantic content\n\n## Full Email Content Without Attachments\nGraph content',
    );
  });

  it('retains original text for semantic-only result', async () => {
    const semanticResult = makeUniqueResult('email-1', { text: 'Unique body' });

    semanticSearchQuery.run.mockResolvedValue({ results: [semanticResult] });
    msGraphKqlQuery.run.mockResolvedValue([]);

    const result = await instance.run(testUserId, {
      semanticSearchParams: { search: 'test', conditions: [], limit: 10 },
      msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
    });

    expect(result[0]?.text).toBe('Unique body');
  });

  it('sets formatted graph section text for graph-only result', async () => {
    const graphResult = makeGraphResult('email-1', { text: 'Graph body' });

    semanticSearchQuery.run.mockResolvedValue({ results: [] });
    msGraphKqlQuery.run.mockResolvedValue([graphResult]);

    const result = await instance.run(testUserId, {
      semanticSearchParams: { search: 'test', conditions: [], limit: 10 },
      msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
    });

    expect(result[0]?.text).toBe('## Full Email Content Without Attachments\nGraph body');
  });

  it('email matched by both backends appears exactly once in output', async () => {
    const semanticResult = makeUniqueResult('email-shared');
    const graphResult = makeGraphResult('email-shared');

    semanticSearchQuery.run.mockResolvedValue({ results: [semanticResult] });
    msGraphKqlQuery.run.mockResolvedValue([graphResult]);

    const result = await instance.run(testUserId, {
      semanticSearchParams: { search: 'test', conditions: [], limit: 10 },
      msGraphSearchParams: { queries: [{ kqlQuery: 'test' }] },
    });

    expect(result).toHaveLength(1);
    expect(result[0]?.backend).toBe(SearchBackend.Unique);
  });
});
