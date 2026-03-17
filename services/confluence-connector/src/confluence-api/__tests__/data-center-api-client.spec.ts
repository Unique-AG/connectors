import { Readable } from 'node:stream';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../../config';
import type { RateLimitedHttpClient } from '../../utils/rate-limited-http-client';
import { DataCenterConfluenceApiClient } from '../data-center-api-client';
import { type ConfluencePage, ContentType } from '../types/confluence-api.types';

const BASE_URL = 'https://dc.example.com';

const mockAuth = { acquireToken: vi.fn().mockResolvedValue('dc-token') };

const mockHttpClient = {
  rateLimitedRequest: vi.fn(),
  rateLimitedStreamRequest: vi.fn(),
} as unknown as RateLimitedHttpClient;

const mockConfig: ConfluenceConfig = {
  baseUrl: BASE_URL,
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
  instanceType: 'data-center',
  auth: { mode: 'pat', token: { expose: () => 'tok' } },
} as unknown as ConfluenceConfig;

function makePage(overrides: Record<string, unknown> = {}) {
  return {
    id: '100',
    title: 'Test Page',
    type: ContentType.PAGE,
    space: { id: 's1', key: 'SP', name: 'Space' },
    version: { when: '2024-01-01' },
    _links: { webui: '/pages/viewpage.action?pageId=100' },
    metadata: { labels: { results: [{ name: 'sync' }] } },
    ...overrides,
  };
}

describe('DataCenterConfluenceApiClient', () => {
  let client: DataCenterConfluenceApiClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = new DataCenterConfluenceApiClient(mockConfig, mockAuth as never, mockHttpClient);
  });

  describe('searchPagesByLabel', () => {
    it('constructs CQL with both labels and space.type=global filter', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('label="sync"');
      expect(decodedUrl).toContain('label="sync-all"');
      expect(decodedUrl).toContain('space.type=global');
      expect(decodedUrl).toContain('type != attachment');
    });

    it('uses /rest/api/content/search with os_authType=basic', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).toContain('/rest/api/content/search');
      expect(url).toContain('os_authType=basic');
    });

    it('includes collaboration space type in filter', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('space.type=collaboration');
    });

    it('uses limit=100 for search pages', async () => {
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
    it('uses direct content endpoint with os_authType=basic', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce(makePage({ id: '42' }));

      await client.getPageById('42');

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).toContain('/rest/api/content/42');
      expect(url).toContain('os_authType=basic');
      expect(url).toContain('expand=body.storage,version,space,metadata.labels');
    });

    it('returns the page when response has a valid id', async () => {
      const page = makePage({ id: '42' });
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce(page);

      const result = await client.getPageById('42');

      expect(result).toEqual(page);
    });

    it('returns null for null response', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce(null);

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });

    it('returns null for undefined response', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce(undefined);

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });

    it('returns null for non-object response', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce('not-an-object');

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });

    it('returns null when id is not a string', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        id: 123,
        title: 'P',
      });

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });
  });

  describe('getDescendantPages', () => {
    it('returns empty array for empty rootIds', async () => {
      const result = await client.getDescendantPages([]);

      expect(result).toEqual([]);
      expect(mockHttpClient.rateLimitedRequest).not.toHaveBeenCalled();
    });

    it('uses CQL ancestor IN (...) with os_authType=basic for single root ID', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.getDescendantPages(['55']);

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('ancestor IN (55)');
      expect(url).toContain('os_authType=basic');
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

    it('paginates results via _links.next', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest)
        .mockResolvedValueOnce({
          results: [makePage({ id: '10' }) as ConfluencePage],
          _links: { next: '/rest/api/content/search?cql=ancestor%3D55&start=25' },
        })
        .mockResolvedValueOnce({
          results: [makePage({ id: '11' }) as ConfluencePage],
          _links: {},
        });

      const results = await client.getDescendantPages(['55']);

      expect(results).toHaveLength(2);
      expect(results[0]?.id).toBe('10');
      expect(results[1]?.id).toBe('11');
    });
  });

  describe('buildPageWebUrl', () => {
    it('builds viewpage URL with page id', () => {
      const page = makePage({ id: '99' });

      const url = client.buildPageWebUrl(page);

      expect(url).toBe(`${BASE_URL}/pages/viewpage.action?pageId=99`);
    });
  });

  describe('buildAttachmentWebUrl', () => {
    it('builds attachment preview URL with viewpageattachments.action', () => {
      const url = client.buildAttachmentWebUrl('327683', '327685', 'lock-icon.png');

      expect(url).toBe(
        `${BASE_URL}/pages/viewpageattachments.action?pageId=327683&preview=%2F327683%2F327685%2Flock-icon.png`,
      );
    });

    it('does not strip any prefix from Data Center attachment IDs', () => {
      const url = client.buildAttachmentWebUrl('100', '200', 'file.pdf');

      expect(url).toContain('preview=%2F100%2F200%2Ffile.pdf');
    });

    it('encodes special characters in attachment title', () => {
      const url = client.buildAttachmentWebUrl('100', '200', 'report (final).pdf');

      expect(url).toContain('preview=%2F100%2F200%2Freport%20(final).pdf');
    });
  });

  describe('attachmentsEnabled option', () => {
    it('includes attachment expand fields when attachmentsEnabled is true', async () => {
      const clientWithAttachments = new DataCenterConfluenceApiClient(
        mockConfig,
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

    it('parses pages with children but without attachment field', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [makePage({ children: {} })],
        _links: {},
      });

      const pages = await client.searchPagesByLabel();

      expect(pages).toHaveLength(1);
      expect(pages[0]?.children?.attachment).toBeUndefined();
    });
  });

  describe('fetchMoreAttachments', () => {
    it('fetches remaining attachments when page has more than initial limit', async () => {
      const clientWithAttachments = new DataCenterConfluenceApiClient(
        mockConfig,
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
      expect(paginationUrl).toContain(`${BASE_URL}/rest/api/content/100/child/attachment`);
    });

    it('does not fetch remaining attachments when size < limit', async () => {
      const clientWithAttachments = new DataCenterConfluenceApiClient(
        mockConfig,
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
    it('builds download URL with baseUrl prefix using downloadPath', async () => {
      const mockStream = new Readable({ read() {} });
      vi.mocked(mockHttpClient.rateLimitedStreamRequest).mockResolvedValueOnce(mockStream);

      await client.getAttachmentDownloadStream(
        'att456',
        '123',
        '/download/attachments/123/report.pdf?version=1&api=v2',
      );

      expect(mockHttpClient.rateLimitedStreamRequest).toHaveBeenCalledWith(
        `${BASE_URL}/download/attachments/123/report.pdf?version=1&api=v2`,
        { Authorization: 'Bearer dc-token' },
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
