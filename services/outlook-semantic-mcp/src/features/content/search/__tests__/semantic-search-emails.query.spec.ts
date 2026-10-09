import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SearchConditionSchema, SearchEmailsInputSchema } from '../search-conditions.dto';
import { SearchBackend, SearchPageStatus } from '../search-results.types';
import { SemanticSearchEmailsQuery } from '../semantic-search-emails.query';

describe('SearchConditionSchema', () => {
  it('accepts a condition with a valid filter field', () => {
    const result = SearchConditionSchema.safeParse({
      hasAttachments: { value: 'true', operator: 'equals' },
    });

    expect(result.success).toBe(true);
  });

  it('accepts a condition without mailbox (existing behavior)', () => {
    const result = SearchConditionSchema.safeParse({
      hasAttachments: { value: 'false', operator: 'equals' },
    });

    expect(result.success).toBe(true);
  });

  it('fails the refine when an empty object is provided', () => {
    const result = SearchConditionSchema.safeParse({});

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.message).toMatch(/Invalid search condition/);
    }
  });
});

describe('SearchEmailsInputSchema', () => {
  it('accepts a valid mailbox email alongside a search field', () => {
    const result = SearchEmailsInputSchema.safeParse({
      search: 'quarterly report',
      mailbox: 'alice@example.com',
    });

    expect(result.success).toBe(true);
  });

  it('rejects a non-email value for mailbox', () => {
    const result = SearchEmailsInputSchema.safeParse({
      search: 'quarterly report',
      mailbox: 'not-an-email',
    });

    expect(result.success).toBe(false);
  });

  it('accepts when mailbox is omitted', () => {
    const result = SearchEmailsInputSchema.safeParse({
      search: 'quarterly report',
    });

    expect(result.success).toBe(true);
  });
});

const testUserId = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

const OWN_EMAIL = 'own@example.com';
const OWN_PROVIDER_ID = 'own-provider-id';
const DELEGATED_EMAIL = 'delegated@example.com';
const DELEGATED_PROVIDER_ID = 'delegated-provider-id';
const DELEGATED_DIR_ID = 'dir-1';

function makeSearchItem(id: string, chunkId = `chunk-${id}`) {
  return {
    id,
    chunkId,
    title: `Email ${id}`,
    url: null,
    metadata: {},
    order: 0,
    text: `Content of ${id}`,
  };
}

function createMockQuery(
  opts: {
    delegatedAccesses?: {
      ownerUserEmail: string;
      ownerUserId: string;
      ownerProviderUserId: string;
      msGraphDirectoryIds: string[];
    }[];
    searchResults?: ReturnType<typeof makeSearchItem>[][];
    searchErrors?: (Error | null)[];
  } = {},
) {
  const { delegatedAccesses = [], searchResults = [[]], searchErrors = [] } = opts;

  // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
  const getDelegatedAccessQuery = { run: vi.fn().mockResolvedValue(delegatedAccesses) } as any;

  let searchCallIndex = 0;
  const contentSearch = vi.fn().mockImplementation(() => {
    const err = searchErrors[searchCallIndex];
    const results = searchResults[searchCallIndex] ?? [];
    searchCallIndex++;
    if (err) {
      return Promise.reject(err);
    }
    return Promise.resolve(results);
  });

  const scopesGetByExternalIds = vi
    .fn()
    .mockImplementation((externalIds: string[]) =>
      Promise.resolve(externalIds.map((externalId) => ({ externalId, id: `scope:${externalId}` }))),
    );

  const getUserProfileQuery = {
    run: vi.fn().mockResolvedValue({
      id: 'user-profile-id',
      email: OWN_EMAIL,
      providerUserId: OWN_PROVIDER_ID,
    }),
  };

  const sanitize = {
    run: vi
      .fn()
      .mockImplementation((_id: string, conditions: unknown) =>
        Promise.resolve({ conditions, searchSummary: undefined }),
      ),
  };

  const apiObj = {
    content: { search: contentSearch },
    scopes: { getByExternalIds: scopesGetByExternalIds },
  };
  // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
  const apiMock = apiObj as any;
  // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
  const profileMock = getUserProfileQuery as any;
  // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
  const sanitizeMock = sanitize as any;
  // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
  const buildWebLinksMock = { run: vi.fn().mockResolvedValue(new Map()) } as any;
  const instance = new SemanticSearchEmailsQuery(
    getDelegatedAccessQuery,
    apiMock,
    profileMock,
    sanitizeMock,
    buildWebLinksMock,
  );

  return { instance, contentSearch };
}

const baseInput = { search: 'test query', limit: 50 };
const delegatedAccess = {
  ownerUserEmail: DELEGATED_EMAIL,
  ownerUserId: 'delegated-user-id',
  ownerProviderUserId: DELEGATED_PROVIDER_ID,
  msGraphDirectoryIds: [DELEGATED_DIR_ID],
};

describe('SemanticSearchEmailsQuery', () => {
  describe('mailbox branch filtering', () => {
    it('searches both own and delegated branches when mailbox is unset', async () => {
      const { instance, contentSearch } = createMockQuery({
        delegatedAccesses: [delegatedAccess],
        searchResults: [[]],
      });

      await instance.run(testUserId, [baseInput]);

      expect(contentSearch).toHaveBeenCalledOnce();
      const metaDataFilter = contentSearch.mock.calls?.[0]?.[0]?.metaDataFilter;
      expect(metaDataFilter.or).toHaveLength(2);
    });

    it('searches only own branch when mailbox matches own email', async () => {
      const { instance, contentSearch } = createMockQuery({
        delegatedAccesses: [delegatedAccess],
        searchResults: [[]],
      });

      await instance.run(testUserId, [{ ...baseInput, mailbox: OWN_EMAIL }]);

      expect(contentSearch).toHaveBeenCalledOnce();
      const metaDataFilter = contentSearch.mock.calls?.[0]?.[0]?.metaDataFilter;
      expect(metaDataFilter.or).toHaveLength(1);
      expect(metaDataFilter.or[0].and[0].value).toContain(OWN_PROVIDER_ID);
    });

    it('searches only delegated branch when mailbox matches delegated email', async () => {
      const { instance, contentSearch } = createMockQuery({
        delegatedAccesses: [delegatedAccess],
        searchResults: [[]],
      });

      await instance.run(testUserId, [{ ...baseInput, mailbox: DELEGATED_EMAIL }]);

      expect(contentSearch).toHaveBeenCalledOnce();
      const metaDataFilter = contentSearch.mock.calls?.[0]?.[0]?.metaDataFilter;
      expect(metaDataFilter.or).toHaveLength(1);
      expect(metaDataFilter.or[0].and[0].value).toContain(DELEGATED_PROVIDER_ID);
    });

    it('makes no API call when mailbox matches no accessible branch', async () => {
      const { instance, contentSearch } = createMockQuery({
        delegatedAccesses: [delegatedAccess],
      });

      const { results } = await instance.run(testUserId, [
        { ...baseInput, mailbox: 'unknown@example.com' },
      ]);

      expect(contentSearch).not.toHaveBeenCalled();
      expect(results).toEqual([]);
    });

    it('returns no page and explains why when the mailbox is not accessible', async () => {
      const { instance } = createMockQuery({ delegatedAccesses: [delegatedAccess] });

      const { pages, searchSummary } = await instance.run(testUserId, [
        { ...baseInput, mailbox: 'unknown@example.com' },
      ]);

      expect(pages).toEqual([]);
      expect(searchSummary).toBe(
        'Semantic search "test query" did not run: unknown@example.com is not a mailbox you can access.',
      );
    });
  });

  describe('multi-input execution', () => {
    it('fires one search per input in parallel', async () => {
      const { instance, contentSearch } = createMockQuery({
        searchResults: [[makeSearchItem('a')], [makeSearchItem('b')]],
      });

      const { results } = await instance.run(testUserId, [
        { search: 'query A', limit: 50 },
        { search: 'query B', limit: 50 },
      ]);

      expect(contentSearch).toHaveBeenCalledTimes(2);
      expect(results).toHaveLength(2);
    });

    it('returns empty results for a failed search and continues with the others', async () => {
      const { instance, contentSearch } = createMockQuery({
        searchResults: [[], [makeSearchItem('b')]],
        searchErrors: [new Error('search failed'), null],
      });

      const { results } = await instance.run(testUserId, [
        { search: 'failing query', limit: 50 },
        { search: 'succeeding query', limit: 50 },
      ]);

      expect(contentSearch).toHaveBeenCalledTimes(2);
      expect(results).toHaveLength(1);
      expect(results[0]?.uniqueContentId).toBe('b');
    });

    it('deduplicates results across inputs by uniqueContentId, first occurrence wins', async () => {
      const sharedItem = makeSearchItem('shared');
      const { instance } = createMockQuery({
        searchResults: [
          [{ ...sharedItem, text: 'from first search' }],
          [{ ...sharedItem, text: 'from second search' }],
        ],
      });

      const { results } = await instance.run(testUserId, [
        { search: 'query A', limit: 50 },
        { search: 'query B', limit: 50 },
      ]);

      expect(results).toHaveLength(1);
      expect(results[0]?.text).toBe('from first search');
    });

    it('returns every email of every search without a count cap', async () => {
      const itemsA = Array.from({ length: 50 }, (_, i) => makeSearchItem(`a-${i}`));
      const itemsB = Array.from({ length: 50 }, (_, i) => makeSearchItem(`b-${i}`));

      const { instance } = createMockQuery({ searchResults: [itemsA, itemsB] });

      const { results } = await instance.run(testUserId, [
        { search: 'query A', limit: 50 },
        { search: 'query B', limit: 50 },
      ]);

      expect(results).toHaveLength(100);
    });
  });

  describe('pagination', () => {
    const fullPage = (prefix: string, size: number) =>
      Array.from({ length: size }, (_, i) => makeSearchItem(`${prefix}-${i}`));

    it('requests the first page, page 1, with the page size as chunk limit', async () => {
      const { instance, contentSearch } = createMockQuery();

      await instance.run(testUserId, [{ search: 'q', limit: 25 }]);

      expect(contentSearch.mock.calls[0]?.[0]).toMatchObject({ limit: 25, page: 1 });
    });

    it('requests 50 chunks per page when no limit is given', async () => {
      const { instance, contentSearch } = createMockQuery();

      await instance.run(testUserId, [{ search: 'q', limit: undefined }]);

      expect(contentSearch.mock.calls[0]?.[0]).toMatchObject({ limit: 50, page: 1 });
    });

    it('keeps paging when a page holds fewer chunks than the page size', async () => {
      const { instance } = createMockQuery({ searchResults: [fullPage('a', 3)] });

      const { pages } = await instance.run(testUserId, [{ search: 'q', limit: 25 }]);

      expect(pages[0]).toMatchObject({
        status: SearchPageStatus.HasMore,
        continuation: { page: 2, seenChunkIds: ['chunk-a-0', 'chunk-a-1', 'chunk-a-2'] },
      });
    });

    it('returns a complete page when the search returns no chunks', async () => {
      const { instance } = createMockQuery({ searchResults: [[]] });

      const { pages } = await instance.run(testUserId, [{ search: 'q', limit: 25 }]);

      expect(pages).toEqual([
        {
          backend: SearchBackend.Unique,
          query: 'q',
          mailbox: undefined,
          status: SearchPageStatus.Complete,
        },
      ]);
    });

    it('returns a hasMore page continuing at the next page when the page is full', async () => {
      const { instance } = createMockQuery({ searchResults: [fullPage('a', 2)] });

      const { pages } = await instance.run(testUserId, [{ search: 'q', limit: 2 }]);

      expect(pages[0]).toMatchObject({
        status: SearchPageStatus.HasMore,
        continuation: {
          backend: SearchBackend.Unique,
          input: { search: 'q', limit: 2 },
          page: 2,
          seenChunkIds: ['chunk-a-0', 'chunk-a-1'],
        },
      });
    });

    it('reports a failed search with a continuation at the same position', async () => {
      const { instance } = createMockQuery({ searchErrors: [new Error('search failed')] });

      const { pages } = await instance.run(testUserId, [{ search: 'q', limit: 25 }]);

      expect(pages[0]).toMatchObject({
        status: SearchPageStatus.Failed,
        continuation: { page: 1, seenChunkIds: [] },
        retryCursorId: undefined,
      });
    });

    describe('fetchNextPages', () => {
      const storedCursor = (overrides: Record<string, unknown> = {}) => ({
        id: 'search_cursor_1',
        createdAt: new Date(),
        payload: {
          backend: SearchBackend.Unique as const,
          input: { search: 'q', limit: 2 },
          page: 2,
          seenChunkIds: ['chunk-a-0', 'chunk-a-1'],
          ...overrides,
        },
      });

      it('requests the stored page and drops only chunks already returned on earlier pages', async () => {
        const { instance, contentSearch } = createMockQuery({
          searchResults: [
            [
              makeSearchItem('a-1'),
              makeSearchItem('a-0', 'chunk-a-0-second'),
              makeSearchItem('b-0'),
            ],
          ],
        });

        const { results, pages } = await instance.fetchNextPages(testUserId, [storedCursor()]);

        expect(contentSearch.mock.calls[0]?.[0]).toMatchObject({ limit: 2, page: 2 });
        expect(results.map((r) => [r.uniqueContentId, r.text])).toEqual([
          ['a-0', 'Content of a-0'],
          ['b-0', 'Content of b-0'],
        ]);
        expect(pages[0]).toMatchObject({
          status: SearchPageStatus.HasMore,
          continuation: {
            page: 3,
            seenChunkIds: ['chunk-a-0', 'chunk-a-1', 'chunk-a-0-second', 'chunk-b-0'],
          },
        });
      });

      it('keeps paging when every chunk of a page was already returned', async () => {
        const { instance } = createMockQuery({ searchResults: [[makeSearchItem('a-0')]] });

        const { results, pages } = await instance.fetchNextPages(testUserId, [storedCursor()]);

        expect(results).toEqual([]);
        expect(pages[0]).toMatchObject({
          status: SearchPageStatus.HasMore,
          continuation: { page: 3, seenChunkIds: ['chunk-a-0', 'chunk-a-1'] },
        });
      });

      it('keeps the same cursor id when the search fails again', async () => {
        const { instance } = createMockQuery({ searchErrors: [new Error('search failed')] });

        const { pages } = await instance.fetchNextPages(testUserId, [storedCursor()]);

        expect(pages[0]).toMatchObject({
          status: SearchPageStatus.Failed,
          retryCursorId: 'search_cursor_1',
          continuation: { page: 2 },
        });
      });

      it('reports accessRevoked when the mailbox is no longer accessible', async () => {
        const { instance, contentSearch } = createMockQuery();

        const { pages } = await instance.fetchNextPages(testUserId, [
          storedCursor({ input: { search: 'q', limit: 2, mailbox: DELEGATED_EMAIL } }),
        ]);

        expect(contentSearch).not.toHaveBeenCalled();
        expect(pages[0]?.status).toBe(SearchPageStatus.AccessRevoked);
      });

      it('completes after the fourth page even when more chunks exist', async () => {
        const { instance } = createMockQuery({ searchResults: [fullPage('z', 50)] });

        const { results, pages } = await instance.fetchNextPages(testUserId, [
          storedCursor({ input: { search: 'q', limit: 50 }, page: 4, seenChunkIds: [] }),
        ]);

        expect(results).toHaveLength(50);
        expect(pages[0]?.status).toBe(SearchPageStatus.Complete);
        expect(pages[0]?.continuation).toBeUndefined();
      });

      it('continues after the third page', async () => {
        const { instance } = createMockQuery({ searchResults: [fullPage('z', 50)] });

        const { pages } = await instance.fetchNextPages(testUserId, [
          storedCursor({ input: { search: 'q', limit: 50 }, page: 3, seenChunkIds: [] }),
        ]);

        expect(pages[0]).toMatchObject({
          status: SearchPageStatus.HasMore,
          continuation: { page: 4 },
        });
      });
    });
  });
});
