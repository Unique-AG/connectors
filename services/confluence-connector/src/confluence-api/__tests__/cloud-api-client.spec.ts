import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../../config';
import type { RateLimitedHttpClient } from '../../utils/rate-limited-http-client';
import { CloudConfluenceApiClient } from '../cloud-api-client';
import { type ConfluencePage, ContentType } from '../types/confluence-api.types';

const BASE_URL = 'https://cloud.example.com';
const CLOUD_ID = 'test-cloud-id';
const API_BASE_URL = `https://api.atlassian.com/ex/confluence/${CLOUD_ID}`;

const mockAuth = { acquireToken: vi.fn().mockResolvedValue('cloud-token') };

const mockHttpClient = {
  rateLimitedRequest: vi.fn(),
} as unknown as RateLimitedHttpClient;

const mockConfig: ConfluenceConfig = {
  baseUrl: BASE_URL,
  cloudId: CLOUD_ID,
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
  instanceType: 'cloud',
  auth: { mode: 'oauth_2lo', clientId: 'cid', clientSecret: { expose: () => 'sec' } },
} as unknown as ConfluenceConfig;

function makePage(overrides: Record<string, unknown> = {}): ConfluencePage {
  return {
    id: '100',
    title: 'Test Page',
    type: ContentType.PAGE,
    space: { id: 's1', key: 'SP', name: 'Space' },
    version: { when: '2024-01-01' },
    _links: { webui: '/spaces/SP/pages/100/Test+Page' },
    metadata: { labels: { results: [{ name: 'sync' }] } },
    ...overrides,
  } as ConfluencePage;
}

describe('CloudConfluenceApiClient', () => {
  let client: CloudConfluenceApiClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = new CloudConfluenceApiClient(mockConfig as never, mockAuth as never, mockHttpClient);
  });

  describe('searchPagesByLabel', () => {
    it('constructs CQL with global and collaboration space type filter', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('(space.type=global OR space.type=collaboration)');
      expect(decodedUrl).toContain('label="sync"');
      expect(decodedUrl).toContain('label="sync-all"');
      expect(decodedUrl).toContain('type != attachment');
    });

    it('uses api.atlassian.com/ex/confluence/{cloudId} base URL without os_authType', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).toContain(`${API_BASE_URL}/wiki/rest/api/content/search`);
      expect(url).not.toContain('os_authType');
    });

    it('uses limit=25 for search', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).toContain('limit=25');
    });
  });

  describe('getPageById', () => {
    it('uses CQL search endpoint with id filter', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [makePage({ id: '77' })],
        _links: {},
      });

      await client.getPageById('77');

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).toContain(`${API_BASE_URL}/wiki/rest/api/content/search`);
      expect(url).toContain('cql=id%3D77');
      expect(url).toContain('expand=body.storage,version,space,metadata.labels');
    });

    it('returns first result from paginated response', async () => {
      const page = makePage({ id: '77', title: 'Found' });
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [page],
        _links: {},
      });

      const result = await client.getPageById('77');

      expect(result).toEqual(page);
    });

    it('returns null for non-object body', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce('not-an-object');

      await expect(client.getPageById('1')).rejects.toThrow();
    });

    it('returns null for empty results array', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });

    it('returns null when first result has no string id', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [{ id: 123, title: 'Bad' }],
        _links: {},
      });

      await expect(client.getPageById('1')).rejects.toThrow();
    });

    it('returns null when body has no results property', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({ data: [] });

      await expect(client.getPageById('1')).rejects.toThrow();
    });
  });

  describe('getDescendantPages', () => {
    it('returns empty array for empty rootIds input', async () => {
      const result = await client.getDescendantPages([]);

      expect(result).toEqual([]);
      expect(mockHttpClient.rateLimitedRequest).not.toHaveBeenCalled();
    });

    it('uses CQL ancestor IN (...) for a single root ID', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.getDescendantPages(['42']);

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('ancestor IN (42)');
    });

    it('uses CQL ancestor IN (...) for multiple root IDs', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.getDescendantPages(['10', '20']);

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('ancestor IN (10,20)');
    });

    it('includes type != attachment in CQL', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.getDescendantPages(['99']);

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('type != attachment');
    });

    it('uses api.atlassian.com/ex/confluence/{cloudId} base URL', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.getDescendantPages(['5']);

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).toContain(`${API_BASE_URL}/wiki/rest/api/content/search`);
    });

    it('paginates results via _links.next', async () => {
      const nextPath = '/wiki/rest/api/content/search?cql=ancestor%3D5&start=25';
      vi.mocked(mockHttpClient.rateLimitedRequest)
        .mockResolvedValueOnce({
          results: [makePage({ id: 'p1' })],
          _links: { next: nextPath },
        })
        .mockResolvedValueOnce({
          results: [makePage({ id: 'p2' })],
          _links: {},
        });

      const result = await client.getDescendantPages(['5']);

      expect(result).toHaveLength(2);
      expect(result[0]?.id).toBe('p1');
      expect(result[1]?.id).toBe('p2');
      const paginatedUrl = vi.mocked(mockHttpClient.rateLimitedRequest).mock
        .calls[1]?.[0] as string;
      expect(paginatedUrl).toBe(`${API_BASE_URL}${nextPath}`);
    });
  });

  describe('buildPageWebUrl', () => {
    it('builds Cloud URL with /wiki prefix and _links.webui', () => {
      const page = makePage({ _links: { webui: '/spaces/SP/pages/100/Test+Page' } });

      const url = client.buildPageWebUrl(page);

      expect(url).toBe(`${BASE_URL}/wiki/spaces/SP/pages/100/Test+Page`);
    });
  });
});
