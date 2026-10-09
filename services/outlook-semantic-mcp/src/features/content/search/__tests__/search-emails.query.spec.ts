import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import type { GetMailboxTimezoneQuery } from '~/features/user-utils/get-mailbox-timezone.query';
import {
  convertUserProfileIdToTypeId,
  type UserProfileTypeID,
} from '~/utils/convert-user-profile-id-to-type-id';
import type { SearchCursorRepository } from '../cursors/search-cursor.repository';
import type { MsGraphKqlSearchEmailsQuery } from '../ms-graph-kql-search-emails.query';
import { SearchEmailsQuery } from '../search-emails.query';
import { SearchBackend, SearchEmailResult, SearchPageStatus } from '../search-results.types';
import type { SemanticSearchEmailsQuery } from '../semantic-search-emails.query';

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
    sourceMailbox: null,
    outlookWebLink: 'https://outlook.com/msg/1',
    receivedDateTime: '2024-01-01T00:00:00Z',
    text: 'Graph body',
    uniqueContentUrl: undefined,
    backend: SearchBackend.MsGraph,
    openEmailParams: { id: emailId, idType: SearchBackend.MsGraph, idIsImmutable: false },
    replyToParams: { inReplyToMessageId: emailId, idIsImmutable: false, isReplyable: true },
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
    sourceMailbox: null,
    outlookWebLink: 'https://outlook.com/msg/2',
    receivedDateTime: '2024-01-01T00:00:00Z',
    text: 'Unique body',
    uniqueContentUrl: 'https://unique.example.com/doc/1',
    backend: SearchBackend.Unique,
    openEmailParams: { id: `content-${emailId}`, idType: SearchBackend.Unique },
    replyToParams: { inReplyToMessageId: emailId, idIsImmutable: true, isReplyable: true },
    ...overrides,
  };
}

describe('SearchEmailsQuery', () => {
  let semanticSearchQuery: { run: Mock; fetchNextPages: Mock };
  let msGraphKqlQuery: { run: Mock; fetchNextPages: Mock };
  let searchCursorRepository: { create: Mock; findForUser: Mock };
  let instance: SearchEmailsQuery;

  beforeEach(() => {
    semanticSearchQuery = { run: vi.fn(), fetchNextPages: vi.fn() };
    msGraphKqlQuery = { run: vi.fn(), fetchNextPages: vi.fn() };
    searchCursorRepository = {
      create: vi
        .fn()
        .mockImplementation((_userProfileId: string, payloads: unknown[]) =>
          Promise.resolve(payloads.map((_, i) => `search_cursor_new_${i}`)),
        ),
      findForUser: vi.fn().mockResolvedValue(new Map()),
    };
    instance = new SearchEmailsQuery(
      semanticSearchQuery as unknown as SemanticSearchEmailsQuery,
      msGraphKqlQuery as unknown as MsGraphKqlSearchEmailsQuery,
      { run: vi.fn().mockResolvedValue(undefined) } as unknown as GetMailboxTimezoneQuery,
      searchCursorRepository as unknown as SearchCursorRepository,
    );
  });

  it('returns only graph results when uniqueSemanticSearchQueries is absent', async () => {
    const graphA = makeGraphResult('email-1');
    const graphB = makeGraphResult('email-2');
    msGraphKqlQuery.run.mockResolvedValue({
      results: [graphA, graphB],
      searchSummary: undefined,
      pages: [],
    });

    const result = await instance.run(testUserId, {
      msGraphKeywordSearchQueries: [{ kqlQuery: 'subject:test' }],
    });

    expect(result.results).toHaveLength(2);
    expect(result.results[0]?.msGraphMessageId).toBe('email-1');
    expect(result.results[1]?.msGraphMessageId).toBe('email-2');
    expect(semanticSearchQuery.run).not.toHaveBeenCalled();
  });

  it('returns empty array when msGraphKeywordSearchQueries is absent', async () => {
    const result = await instance.run(testUserId, {});

    expect(result.results).toEqual([]);
    expect(msGraphKqlQuery.run).not.toHaveBeenCalled();
    expect(semanticSearchQuery.run).not.toHaveBeenCalled();
  });

  it('returns empty array when both backends return no results', async () => {
    semanticSearchQuery.run.mockResolvedValue({ results: [], searchSummary: undefined, pages: [] });
    msGraphKqlQuery.run.mockResolvedValue({ results: [], searchSummary: undefined, pages: [] });

    const result = await instance.run(testUserId, {
      uniqueSemanticSearchQueries: [{ search: 'test', conditions: [], limit: 10 }],
      msGraphKeywordSearchQueries: [{ kqlQuery: 'test' }],
    });

    expect(result.results).toEqual([]);
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

    semanticSearchQuery.run.mockResolvedValue({
      results: semanticResults,
      searchSummary: undefined,
      pages: [],
    });
    msGraphKqlQuery.run.mockResolvedValue({
      results: [...graphMatches, graphOnly],
      searchSummary: undefined,
      pages: [],
    });

    const result = await instance.run(testUserId, {
      uniqueSemanticSearchQueries: [{ search: 'test', conditions: [], limit: 25 }],
      msGraphKeywordSearchQueries: [{ kqlQuery: 'test' }],
    });

    expect(result.results).toHaveLength(23);
    // top20: indices 0-19 (enriched, hadGraphMatch)
    expect(result.results[0]?.msGraphMessageId).toBe('email-0');
    expect(result.results[19]?.msGraphMessageId).toBe('email-19');
    // commonRemainder: index 21 (hadGraphMatch, beyond top20)
    expect(result.results[20]?.msGraphMessageId).toBe('email-21');
    // semanticOnly: index 20 (no graph match, beyond top20)
    expect(result.results[21]?.msGraphMessageId).toBe('email-20');
    // remainingGraph: graph-only
    expect(result.results[22]?.msGraphMessageId).toBe('email-graph-only');
  });

  it('semantic-only results beyond top-20 appear before graph-only results', async () => {
    // 21 semantic results, none overlap with graph
    const semanticResults = Array.from({ length: 21 }, (_, i) =>
      makeUniqueResult(`email-semantic-${i}`),
    );
    const graphOnly = makeGraphResult('email-graph-only');

    semanticSearchQuery.run.mockResolvedValue({
      results: semanticResults,
      searchSummary: undefined,
      pages: [],
    });
    msGraphKqlQuery.run.mockResolvedValue({
      results: [graphOnly],
      searchSummary: undefined,
      pages: [],
    });

    const result = await instance.run(testUserId, {
      uniqueSemanticSearchQueries: [{ search: 'test', conditions: [], limit: 25 }],
      msGraphKeywordSearchQueries: [{ kqlQuery: 'test' }],
    });

    expect(result.results).toHaveLength(22);
    // top20: indices 0-19
    expect(result.results[0]?.msGraphMessageId).toBe('email-semantic-0');
    expect(result.results[19]?.msGraphMessageId).toBe('email-semantic-19');
    // semanticOnly remainder: index 20
    expect(result.results[20]?.msGraphMessageId).toBe('email-semantic-20');
    // graph-only last
    expect(result.results[21]?.msGraphMessageId).toBe('email-graph-only');
  });

  it('enriches text with both sections when email matched by both backends', async () => {
    const semanticResult = makeUniqueResult('email-1', { text: 'Semantic content' });
    const graphResult = makeGraphResult('email-1', { text: 'Graph content' });

    semanticSearchQuery.run.mockResolvedValue({
      results: [semanticResult],
      searchSummary: undefined,
      pages: [],
    });
    msGraphKqlQuery.run.mockResolvedValue({
      results: [graphResult],
      searchSummary: undefined,
      pages: [],
    });

    const result = await instance.run(testUserId, {
      uniqueSemanticSearchQueries: [{ search: 'test', conditions: [], limit: 10 }],
      msGraphKeywordSearchQueries: [{ kqlQuery: 'test' }],
    });

    expect(result.results[0]?.text).toBe(
      '## Semantically Matched Content\nSemantic content\n\n## Preview\nGraph content',
    );
  });

  it('retains original text for semantic-only result', async () => {
    const semanticResult = makeUniqueResult('email-1', { text: 'Unique body' });

    semanticSearchQuery.run.mockResolvedValue({
      results: [semanticResult],
      searchSummary: undefined,
      pages: [],
    });
    msGraphKqlQuery.run.mockResolvedValue({ results: [], searchSummary: undefined, pages: [] });

    const result = await instance.run(testUserId, {
      uniqueSemanticSearchQueries: [{ search: 'test', conditions: [], limit: 10 }],
      msGraphKeywordSearchQueries: [{ kqlQuery: 'test' }],
    });

    expect(result.results[0]?.text).toBe('Unique body');
  });

  it('sets formatted graph section text for graph-only result', async () => {
    const graphResult = makeGraphResult('email-1', { text: 'Graph body' });

    semanticSearchQuery.run.mockResolvedValue({ results: [], searchSummary: undefined, pages: [] });
    msGraphKqlQuery.run.mockResolvedValue({
      results: [graphResult],
      searchSummary: undefined,
      pages: [],
    });

    const result = await instance.run(testUserId, {
      uniqueSemanticSearchQueries: [{ search: 'test', conditions: [], limit: 10 }],
      msGraphKeywordSearchQueries: [{ kqlQuery: 'test' }],
    });

    expect(result.results[0]?.text).toBe('## Preview\nGraph body');
  });

  it('email matched by both backends appears exactly once in output', async () => {
    const semanticResult = makeUniqueResult('email-shared');
    const graphResult = makeGraphResult('email-shared');

    semanticSearchQuery.run.mockResolvedValue({
      results: [semanticResult],
      searchSummary: undefined,
      pages: [],
    });
    msGraphKqlQuery.run.mockResolvedValue({
      results: [graphResult],
      searchSummary: undefined,
      pages: [],
    });

    const result = await instance.run(testUserId, {
      uniqueSemanticSearchQueries: [{ search: 'test', conditions: [], limit: 10 }],
      msGraphKeywordSearchQueries: [{ kqlQuery: 'test' }],
    });

    expect(result.results).toHaveLength(1);
    expect(result.results[0]?.backend).toBe(SearchBackend.Unique);
  });

  describe('pages and cursors', () => {
    const graphContinuation = {
      backend: SearchBackend.MsGraph as const,
      kqlQuery: 'test',
      mailbox: 'own@example.com',
      isDelegated: false,
      url: '/users/own@example.com/messages?$skip=25',
      delivered: 25,
    };
    const graphPage = {
      backend: SearchBackend.MsGraph,
      query: 'test',
      mailbox: 'own@example.com',
    };

    it('stores each continuation as a new cursor and returns its id', async () => {
      msGraphKqlQuery.run.mockResolvedValue({
        results: [],
        searchSummary: undefined,
        pages: [
          { ...graphPage, status: SearchPageStatus.HasMore, continuation: graphContinuation },
          { ...graphPage, mailbox: 'other@example.com', status: SearchPageStatus.Complete },
        ],
      });

      const result = await instance.run(testUserId, {
        msGraphKeywordSearchQueries: [{ kqlQuery: 'test' }],
      });

      expect(searchCursorRepository.create).toHaveBeenCalledWith(testUserId.toString(), [
        graphContinuation,
      ]);
      expect(result.pages).toEqual([
        { ...graphPage, status: SearchPageStatus.HasMore, cursorId: 'search_cursor_new_0' },
        {
          ...graphPage,
          mailbox: 'other@example.com',
          status: SearchPageStatus.Complete,
          cursorId: undefined,
        },
      ]);
      expect(result.hasMore).toBe(true);
    });

    it('returns hasMore false when no page can be continued', async () => {
      msGraphKqlQuery.run.mockResolvedValue({
        results: [],
        searchSummary: undefined,
        pages: [{ ...graphPage, status: SearchPageStatus.CeilingReached }],
      });

      const result = await instance.run(testUserId, {
        msGraphKeywordSearchQueries: [{ kqlQuery: 'test' }],
      });

      expect(result.hasMore).toBe(false);
    });

    it('returns the existing cursor id for a page that must be retried, without counting it as hasMore', async () => {
      searchCursorRepository.findForUser.mockResolvedValue(
        new Map([
          [
            'search_cursor_old',
            { id: 'search_cursor_old', payload: graphContinuation, createdAt: new Date() },
          ],
        ]),
      );
      msGraphKqlQuery.fetchNextPages.mockResolvedValue({
        results: [],
        searchSummary: undefined,
        pages: [
          {
            ...graphPage,
            status: SearchPageStatus.Throttled,
            retryAfterSeconds: 7,
            continuation: graphContinuation,
            retryCursorId: 'search_cursor_old',
          },
        ],
      });

      const result = await instance.fetchNextPages(testUserId, ['search_cursor_old']);

      expect(result.pages).toEqual([
        {
          ...graphPage,
          status: SearchPageStatus.Throttled,
          retryAfterSeconds: 7,
          cursorId: 'search_cursor_old',
        },
      ]);
      expect(result.hasMore).toBe(false);
    });

    it('returns hasMore true when a page can continue next to a throttled page', async () => {
      msGraphKqlQuery.run.mockResolvedValue({
        results: [],
        searchSummary: undefined,
        pages: [
          { ...graphPage, status: SearchPageStatus.HasMore, continuation: graphContinuation },
          {
            ...graphPage,
            mailbox: 'other@example.com',
            status: SearchPageStatus.Throttled,
            retryAfterSeconds: 7,
            continuation: { ...graphContinuation, mailbox: 'other@example.com' },
          },
        ],
      });

      const result = await instance.run(testUserId, {
        msGraphKeywordSearchQueries: [{ kqlQuery: 'test' }],
      });

      expect(result.pages.map(({ status, cursorId }) => ({ status, cursorId }))).toEqual([
        { status: SearchPageStatus.HasMore, cursorId: 'search_cursor_new_0' },
        { status: SearchPageStatus.Throttled, cursorId: 'search_cursor_new_1' },
      ]);
      expect(result.hasMore).toBe(true);
    });

    it('continues each stored cursor on its own backend', async () => {
      const uniqueContinuation = {
        backend: SearchBackend.Unique as const,
        input: { search: 'semantic question', limit: 25 },
        page: 1,
        seenContentIds: [],
      };
      searchCursorRepository.findForUser.mockResolvedValue(
        new Map<string, unknown>([
          [
            'search_cursor_graph',
            { id: 'search_cursor_graph', payload: graphContinuation, createdAt: new Date() },
          ],
          [
            'search_cursor_unique',
            { id: 'search_cursor_unique', payload: uniqueContinuation, createdAt: new Date() },
          ],
        ]),
      );
      // Each backend answers only for the cursors it was given, so a cursor sent to the wrong
      // backend would show up as a missing or misattributed page.
      msGraphKqlQuery.fetchNextPages.mockImplementation(
        async (_userId: unknown, cursors: { payload: typeof graphContinuation }[]) => ({
          results: [],
          searchSummary: undefined,
          pages: cursors.map(({ payload }) => ({
            backend: SearchBackend.MsGraph,
            query: payload.kqlQuery,
            mailbox: payload.mailbox,
            status: SearchPageStatus.Complete,
          })),
        }),
      );
      semanticSearchQuery.fetchNextPages.mockImplementation(
        async (_userId: unknown, cursors: { payload: typeof uniqueContinuation }[]) => ({
          results: [],
          searchSummary: undefined,
          pages: cursors.map(({ payload }) => ({
            backend: SearchBackend.Unique,
            query: payload.input.search,
            status: SearchPageStatus.Complete,
          })),
        }),
      );

      const result = await instance.fetchNextPages(testUserId, [
        'search_cursor_graph',
        'search_cursor_unique',
      ]);

      expect(result.pages).toEqual([
        {
          backend: SearchBackend.Unique,
          query: 'semantic question',
          status: SearchPageStatus.Complete,
          cursorId: undefined,
        },
        {
          backend: SearchBackend.MsGraph,
          query: graphContinuation.kqlQuery,
          mailbox: graphContinuation.mailbox,
          status: SearchPageStatus.Complete,
          cursorId: undefined,
        },
      ]);
      expect(result.searchSummary).toBeUndefined();
    });

    it('reports unknown cursor ids in the search notes', async () => {
      const result = await instance.fetchNextPages(testUserId, ['search_cursor_missing']);

      expect(msGraphKqlQuery.fetchNextPages).not.toHaveBeenCalled();
      expect(semanticSearchQuery.fetchNextPages).not.toHaveBeenCalled();
      expect(result.searchSummary).toContain('search_cursor_missing');
      expect(result.hasMore).toBe(false);
    });
  });
});
