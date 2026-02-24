import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../../config';
import type { RateLimitedHttpClient } from '../../utils/rate-limited-http-client';
import { DataCenterConfluenceApiClient } from '../data-center-api-client';
import type { ConfluencePage } from '../types/confluence-api.types';

const MOCK_TOKEN = 'test-bearer-token';
const BASE_URL = 'https://dc.example.com';

const mockAuth = { acquireToken: vi.fn().mockResolvedValue(MOCK_TOKEN) };

const mockHttpClient = {
  rateLimitedRequest: vi.fn(),
} as unknown as RateLimitedHttpClient;

const mockConfig: ConfluenceConfig = {
  baseUrl: BASE_URL,
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
  instanceType: 'data-center',
  auth: { mode: 'pat', token: { expose: () => 'tok' } },
} as unknown as ConfluenceConfig;

function makePage(overrides: Record<string, unknown> = {}): ConfluencePage {
  return {
    id: '1',
    title: 'P',
    type: 'page',
    space: { id: 's1', key: 'SP', name: 'Space' },
    version: { when: '2024-01-01' },
    _links: { webui: '/x' },
    metadata: { labels: { results: [] } },
    ...overrides,
  } as ConfluencePage;
}

describe('ConfluenceApiClient (auth integration)', () => {
  let client: DataCenterConfluenceApiClient;

  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.acquireToken.mockResolvedValue(MOCK_TOKEN);
    client = new DataCenterConfluenceApiClient(mockConfig, mockAuth as never, mockHttpClient);
  });

  describe('auth header injection', () => {
    it('includes Authorization Bearer header on every request', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce(makePage());

      await client.getPageById('1');

      expect(mockHttpClient.rateLimitedRequest).toHaveBeenCalledWith(
        expect.any(String),
        { Authorization: `Bearer ${MOCK_TOKEN}` },
      );
    });

    it('acquires a fresh token before each request', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce(
        makePage({ id: '1', title: 'P' }),
      );
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce(
        makePage({ id: '2', title: 'Q' }),
      );

      await client.getPageById('1');
      await client.getPageById('2');

      expect(mockAuth.acquireToken).toHaveBeenCalledTimes(2);
    });
  });

  describe('pagination via fetchAllPaginated', () => {
    it('follows _links.next until no more pages', async () => {
      const page1 = {
        results: [
          makePage({ id: '1', title: 'A', metadata: { labels: { results: [{ name: 'sync' }] } } }),
        ],
        _links: { next: '/rest/api/content/search?cursor=abc' },
      };
      const page2 = {
        results: [
          makePage({ id: '2', title: 'B', metadata: { labels: { results: [{ name: 'sync' }] } } }),
        ],
        _links: {},
      };

      vi.mocked(mockHttpClient.rateLimitedRequest)
        .mockResolvedValueOnce(page1)
        .mockResolvedValueOnce(page2);

      const results = await client.searchPagesByLabel();

      expect(results).toHaveLength(2);
      expect(results[0]?.id).toBe('1');
      expect(results[1]?.id).toBe('2');
    });

    it('returns results from single page when no next link exists', async () => {
      const singlePage = {
        results: [makePage({ id: '1', title: 'A' })],
        _links: {},
      };

      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce(singlePage);

      const results = await client.searchPagesByLabel();

      expect(results).toHaveLength(1);
      expect(mockHttpClient.rateLimitedRequest).toHaveBeenCalledTimes(1);
    });

    it('prepends baseUrl to next link for subsequent requests', async () => {
      const nextPath = '/rest/api/content/search?cursor=next123';
      const page1 = {
        results: [],
        _links: { next: nextPath },
      };
      const page2 = {
        results: [],
        _links: {},
      };

      vi.mocked(mockHttpClient.rateLimitedRequest)
        .mockResolvedValueOnce(page1)
        .mockResolvedValueOnce(page2);

      await client.searchPagesByLabel();

      expect(mockHttpClient.rateLimitedRequest).toHaveBeenCalledTimes(2);
      const secondCall = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[1];
      expect(secondCall).toBeDefined();
      const secondCallUrl = secondCall?.[0] as string;
      expect(secondCallUrl).toBe(`${BASE_URL}${nextPath}`);
    });
  });
});
