import { Readable } from 'node:stream';
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
  rateLimitedStreamRequest: vi.fn(),
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

    it('uses limit=100 for search', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).toContain('limit=100');
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

  describe('attachmentsEnabled option', () => {
    it('includes attachment expand fields when attachmentsEnabled is true', async () => {
      const clientWithAttachments = new CloudConfluenceApiClient(
        mockConfig as never,
        mockAuth as never,
        mockHttpClient,
        { attachmentsEnabled: true },
      );
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await clientWithAttachments.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).toContain('children.attachment');
      expect(url).toContain('children.attachment.version');
      expect(url).toContain('children.attachment.extensions');
    });

    it('excludes attachment expand fields when attachmentsEnabled is false', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).not.toContain('children.attachment');
    });
  });

  describe('fetchMoreAttachments', () => {
    it('fetches remaining attachments when page has more than initial limit', async () => {
      const clientWithAttachments = new CloudConfluenceApiClient(
        mockConfig as never,
        mockAuth as never,
        mockHttpClient,
        { attachmentsEnabled: true },
      );

      const pageWithPaginatedAttachments = makePage({
        children: {
          attachment: {
            results: [
              {
                id: 'att-1',
                title: 'a.pdf',
                extensions: { mediaType: 'application/pdf', fileSize: 100 },
                version: { when: '2024-01-01' },
                _links: { download: '/d/a.pdf' },
              },
            ],
            size: 25,
            limit: 25,
            _links: { next: '/rest/api/content/100/child/attachment?start=25&limit=25' },
          },
        },
      });

      vi.mocked(mockHttpClient.rateLimitedRequest)
        .mockResolvedValueOnce({
          results: [pageWithPaginatedAttachments],
          _links: {},
        })
        .mockResolvedValueOnce({
          results: [
            {
              id: 'att-2',
              title: 'b.pdf',
              extensions: { mediaType: 'application/pdf', fileSize: 200 },
              version: { when: '2024-01-01' },
              _links: { download: '/d/b.pdf' },
            },
          ],
          _links: {},
        });

      const pages = await clientWithAttachments.searchPagesByLabel();

      expect(pages[0]?.children?.attachment?.results).toHaveLength(2);
      expect(pages[0]?.children?.attachment?.results[1]?.id).toBe('att-2');
      const paginationUrl = vi.mocked(mockHttpClient.rateLimitedRequest).mock
        .calls[1]?.[0] as string;
      expect(paginationUrl).toContain(`${API_BASE_URL}/wiki/rest/api/content/100/child/attachment`);
    });

    it('does not fetch remaining attachments when size < limit', async () => {
      const clientWithAttachments = new CloudConfluenceApiClient(
        mockConfig as never,
        mockAuth as never,
        mockHttpClient,
        { attachmentsEnabled: true },
      );

      const pageWithFewAttachments = makePage({
        children: {
          attachment: {
            results: [
              {
                id: 'att-1',
                title: 'a.pdf',
                extensions: { mediaType: 'application/pdf', fileSize: 100 },
                version: { when: '2024-01-01' },
                _links: { download: '/d/a.pdf' },
              },
            ],
            size: 1,
            limit: 25,
            _links: {},
          },
        },
      });

      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [pageWithFewAttachments],
        _links: {},
      });

      await clientWithAttachments.searchPagesByLabel();

      expect(mockHttpClient.rateLimitedRequest).toHaveBeenCalledTimes(1);
    });
  });

  describe('getAttachmentDownloadStream', () => {
    it('builds v1 REST API download URL with pageId and attachmentId', async () => {
      const mockStream = new Readable({ read() {} });
      vi.mocked(mockHttpClient.rateLimitedStreamRequest).mockResolvedValueOnce(mockStream);

      await client.getAttachmentDownloadStream(
        'att456',
        '123',
        '/download/attachments/123/report.pdf?version=1&api=v2',
      );

      expect(mockHttpClient.rateLimitedStreamRequest).toHaveBeenCalledWith(
        `${API_BASE_URL}/wiki/rest/api/content/123/child/attachment/att456/download`,
        { Authorization: 'Bearer cloud-token' },
      );
    });

    it('returns the stream from the HTTP client', async () => {
      const mockStream = new Readable({ read() {} });
      vi.mocked(mockHttpClient.rateLimitedStreamRequest).mockResolvedValueOnce(mockStream);

      const result = await client.getAttachmentDownloadStream(
        'att789',
        '123',
        '/download/attachments/123/file.txt',
      );

      expect(result).toBe(mockStream);
    });
  });
});
