import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CleanupSearchConditionsForUserQuery } from '../cleanup-search-conditions-for-user.query';
import { SearchConditionSchema, SearchEmailsInputSchema } from '../search-conditions.dto';
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

// biome-ignore lint/suspicious/noExplicitAny: constructor args not needed for this private method
const query = new CleanupSearchConditionsForUserQuery(null as any);

interface MockDirectory {
  providerDirectoryId: string;
  displayName: string;
}

const inboxDir: MockDirectory = { providerDirectoryId: 'inbox-id-123', displayName: 'Inbox' };
const sentDir: MockDirectory = { providerDirectoryId: 'sent-id-456', displayName: 'Sent Items' };

describe('SanitizeSearchConditionsForUserQuery.sanitizeWrongDirectoryIds', () => {
  it('returns the ID unchanged when it exactly matches a providerDirectoryId', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['inbox-id-123'], [inboxDir]);

    expect(result).toEqual({ resolvedIds: ['inbox-id-123'], unrecognized: [] });
  });

  it('resolves a display name fuzzy match above threshold to the correct providerDirectoryId', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['inbox'], [inboxDir]);

    expect(result).toEqual({ resolvedIds: ['inbox-id-123'], unrecognized: [] });
  });

  it('places a string below the similarity threshold into unrecognized', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['xyz123'], [inboxDir]);

    expect(result).toEqual({ resolvedIds: [], unrecognized: ['xyz123'] });
  });

  it('resolves a string at exactly the 80% similarity threshold', () => {
    // "Inboc" vs "Inbox": distance 1, max length 5 → similarity 0.8 (at threshold, should match)
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['Inboc'], [inboxDir]);

    expect(result).toEqual({ resolvedIds: ['inbox-id-123'], unrecognized: [] });
  });

  it('rejects a string just below the 80% similarity threshold', () => {
    // "Inbcc" vs "Inbox": distance 2, max length 5 → similarity 0.6 (below threshold)
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['Inbcc'], [inboxDir]);

    expect(result).toEqual({ resolvedIds: [], unrecognized: ['Inbcc'] });
  });

  it('splits mixed input correctly between resolvedIds and unrecognized', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(
      ['inbox-id-123', 'xyz123'],
      [inboxDir, sentDir],
    );

    expect(result).toEqual({ resolvedIds: ['inbox-id-123'], unrecognized: ['xyz123'] });
  });

  it('places all inputs into unrecognized when none match any directory', () => {
    // biome-ignore lint/suspicious/noExplicitAny: accessing private method for testing
    const result = (query as any).sanitizeWrongDirectoryIds(['foo', 'bar'], [inboxDir, sentDir]);

    expect(result).toEqual({ resolvedIds: [], unrecognized: ['foo', 'bar'] });
  });
});

const testUserId = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

const OWN_EMAIL = 'own@example.com';
const OWN_PROVIDER_ID = 'own-provider-id';
const DELEGATED_EMAIL = 'delegated@example.com';
const DELEGATED_PROVIDER_ID = 'delegated-provider-id';
const DELEGATED_DIR_ID = 'dir-1';

function makeSearchItem(id: string) {
  return {
    id,
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
  const instance = new SemanticSearchEmailsQuery(
    getDelegatedAccessQuery,
    apiMock,
    profileMock,
    sanitizeMock,
  );

  return { instance, contentSearch };
}

const baseInput = { search: 'test query', limit: 200 as const };
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

      await instance.run(testUserId, [baseInput], 100);

      expect(contentSearch).toHaveBeenCalledOnce();
      const metaDataFilter = contentSearch.mock.calls?.[0]?.[0]?.metaDataFilter;
      expect(metaDataFilter.or).toHaveLength(2);
    });

    it('searches only own branch when mailbox matches own email', async () => {
      const { instance, contentSearch } = createMockQuery({
        delegatedAccesses: [delegatedAccess],
        searchResults: [[]],
      });

      await instance.run(testUserId, [{ ...baseInput, mailbox: OWN_EMAIL }], 100);

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

      await instance.run(testUserId, [{ ...baseInput, mailbox: DELEGATED_EMAIL }], 100);

      expect(contentSearch).toHaveBeenCalledOnce();
      const metaDataFilter = contentSearch.mock.calls?.[0]?.[0]?.metaDataFilter;
      expect(metaDataFilter.or).toHaveLength(1);
      expect(metaDataFilter.or[0].and[0].value).toContain(DELEGATED_PROVIDER_ID);
    });

    it('makes no API call when mailbox matches no accessible branch', async () => {
      const { instance, contentSearch } = createMockQuery({
        delegatedAccesses: [delegatedAccess],
      });

      const { results } = await instance.run(
        testUserId,
        [{ ...baseInput, mailbox: 'unknown@example.com' }],
        100,
      );

      expect(contentSearch).not.toHaveBeenCalled();
      expect(results).toEqual([]);
    });
  });

  describe('multi-input execution', () => {
    it('fires one search per input in parallel', async () => {
      const { instance, contentSearch } = createMockQuery({
        searchResults: [[makeSearchItem('a')], [makeSearchItem('b')]],
      });

      const { results } = await instance.run(
        testUserId,
        [
          { search: 'query A', limit: 200 as const },
          { search: 'query B', limit: 200 as const },
        ],
        100,
      );

      expect(contentSearch).toHaveBeenCalledTimes(2);
      expect(results).toHaveLength(2);
    });

    it('returns empty results for a failed search and continues with the others', async () => {
      const { instance, contentSearch } = createMockQuery({
        searchResults: [[], [makeSearchItem('b')]],
        searchErrors: [new Error('search failed'), null],
      });

      const { results } = await instance.run(
        testUserId,
        [
          { search: 'failing query', limit: 200 as const },
          { search: 'succeeding query', limit: 200 as const },
        ],
        100,
      );

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

      const { results } = await instance.run(
        testUserId,
        [
          { search: 'query A', limit: 200 as const },
          { search: 'query B', limit: 200 as const },
        ],
        100,
      );

      expect(results).toHaveLength(1);
      expect(results[0]?.text).toBe('from first search');
    });

    it('caps merged results at 100', async () => {
      const items400 = Array.from({ length: 400 }, (_, i) => makeSearchItem(`a-${i}`));
      const items300 = Array.from({ length: 300 }, (_, i) => makeSearchItem(`b-${i}`));

      const { instance } = createMockQuery({
        searchResults: [items400, items300],
      });

      const { results } = await instance.run(
        testUserId,
        [
          { search: 'query A', limit: 200 as const },
          { search: 'query B', limit: 200 as const },
        ],
        100,
      );

      expect(results).toHaveLength(100);
    });
  });
});
