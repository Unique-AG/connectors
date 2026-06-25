import { Readable } from 'node:stream';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../../config';
import type { RateLimitedHttpClient } from '../../utils/rate-limited-http-client';
import { DataCenterConfluenceApiClient } from '../data-center-api-client';
import { type ConfluencePage, ContentType } from '../types/confluence-api.types';

const BASE_URL = 'https://dc.example.com';

const mockAuth = { getAuthorizationHeader: vi.fn().mockResolvedValue('Bearer dc-token') };

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
    client = new DataCenterConfluenceApiClient(mockConfig, mockAuth as never, mockHttpClient, {
      attachmentsEnabled: false,
    });
  });

  describe('resolveInstanceIdentifier', () => {
    it('calls the applinks manifest endpoint with Accept: application/json and no auth header', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        id: 'dc-instance-uuid',
        name: 'My Confluence',
      });

      await client.resolveInstanceIdentifier();

      expect(mockHttpClient.rateLimitedRequest).toHaveBeenCalledWith(
        `${BASE_URL}/rest/applinks/1.0/manifest`,
        { Accept: 'application/json' },
      );
    });

    it('returns data-center type with id from manifest response', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        id: 'dc-instance-uuid',
        name: 'My Confluence',
      });

      const result = await client.resolveInstanceIdentifier();

      expect(result).toEqual({ type: 'data-center', id: 'dc-instance-uuid' });
    });

    it('throws when manifest response is missing the id field', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        name: 'My Confluence',
      });

      await expect(client.resolveInstanceIdentifier()).rejects.toThrow(
        'did not contain a valid "id" field',
      );
    });

    it('throws when manifest response id is not a string', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        id: 12345,
      });

      await expect(client.resolveInstanceIdentifier()).rejects.toThrow(
        'did not contain a valid "id" field',
      );
    });

    it('throws when manifest response id is an empty string', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        id: '',
      });

      await expect(client.resolveInstanceIdentifier()).rejects.toThrow(
        'did not contain a valid "id" field',
      );
    });

    it('throws when manifest response is null', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce(null);

      await expect(client.resolveInstanceIdentifier()).rejects.toThrow(
        'did not contain a valid "id" field',
      );
    });

    it('propagates HTTP errors from the manifest request', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockRejectedValueOnce(
        new Error('Error response from https://dc.example.com/rest/applinks/1.0/manifest: 500'),
      );

      await expect(client.resolveInstanceIdentifier()).rejects.toThrow('500');
    });
  });

  describe('searchPagesByLabel', () => {
    it('constructs CQL with both labels and only space.type=global filter', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('label="sync"');
      expect(decodedUrl).toContain('label="sync-all"');
      expect(decodedUrl).toContain('AND space.type=global AND');
      expect(decodedUrl).toContain('type != attachment');
    });

    it('uses /rest/api/content/search without os_authType', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).toContain('/rest/api/content/search');
      expect(url).not.toContain('os_authType');
    });

    it('does not include collaboration space type (unsupported by Data Center)', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.searchPagesByLabel();

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).not.toContain('space.type=collaboration');
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
    it('uses direct content endpoint without os_authType', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce(makePage({ id: '42' }));

      await client.getPageById('42');

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url).toContain('/rest/api/content/42');
      expect(url).not.toContain('os_authType');
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

    it('uses CQL ancestor IN (...) without os_authType for single root ID', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await client.getDescendantPages(['55']);

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('ancestor IN (55)');
      expect(url).not.toContain('os_authType');
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

  describe('fetchAttachmentsByPageTitle', () => {
    function clientWithAttachments() {
      return new DataCenterConfluenceApiClient(mockConfig, mockAuth as never, mockHttpClient, {
        attachmentsEnabled: true,
      });
    }

    it('returns null without HTTP when attachmentsEnabled is false', async () => {
      const result = await client.fetchAttachmentsByPageTitle('SP', 'Other Page');

      expect(result).toBeNull();
      expect(mockHttpClient.rateLimitedRequest).not.toHaveBeenCalled();
    });

    it('queries /rest/api/content with URL-encoded spaceKey, title, type=page, and attachment expand', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      await clientWithAttachments().fetchAttachmentsByPageTitle(
        'TST SPACE',
        'Page With "Quotes" & Stuff',
      );

      const url = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls[0]?.[0] as string;
      expect(url.startsWith(`${BASE_URL}/rest/api/content?`)).toBe(true);
      expect(url).toContain('spaceKey=TST%20SPACE');
      expect(url).toContain('title=Page%20With%20%22Quotes%22%20%26%20Stuff');
      expect(url).toContain('type=page');
      expect(url).toContain('expand=metadata.labels,version,space');
      expect(url).toContain('children.attachment');
    });

    it('returns null when the search returns no results', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [],
        _links: {},
      });

      const result = await clientWithAttachments().fetchAttachmentsByPageTitle('SP', 'Missing');

      expect(result).toBeNull();
    });

    it('returns pageId + attachments of the first matching page', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest).mockResolvedValueOnce({
        results: [
          makePage({
            id: '500',
            children: {
              attachment: {
                results: [
                  {
                    id: 'att-x',
                    title: 'x.png',
                    extensions: { mediaType: 'image/png', fileSize: 1234 },
                    version: { when: '2024-01-01' },
                    _links: { download: '/download/attachments/500/x.png' },
                  },
                ],
                size: 1,
                limit: 25,
                _links: {},
              },
            },
          }),
        ],
        _links: {},
      });

      const result = await clientWithAttachments().fetchAttachmentsByPageTitle('SP', 'Other Page');

      expect(result?.pageId).toBe('500');
      expect(result?.attachments).toHaveLength(1);
      expect(result?.attachments[0]?.id).toBe('att-x');
    });

    it('follows _links.next to fetch attachments beyond the initial 25', async () => {
      vi.mocked(mockHttpClient.rateLimitedRequest)
        .mockResolvedValueOnce({
          results: [
            makePage({
              id: '700',
              children: {
                attachment: {
                  results: [
                    {
                      id: 'att-1',
                      title: 'a.png',
                      extensions: { mediaType: 'image/png', fileSize: 1 },
                      version: { when: '2024-01-01' },
                      _links: { download: '/d/a.png' },
                    },
                  ],
                  size: 25,
                  limit: 25,
                  _links: { next: '/rest/api/content/700/child/attachment?start=25' },
                },
              },
            }),
          ],
          _links: {},
        })
        .mockResolvedValueOnce({
          results: [
            {
              id: 'att-2',
              title: 'b.png',
              extensions: { mediaType: 'image/png', fileSize: 2 },
              version: { when: '2024-01-01' },
              _links: { download: '/d/b.png' },
            },
          ],
          _links: {},
        });

      const result = await clientWithAttachments().fetchAttachmentsByPageTitle('SP', 'Other Page');

      const calls = vi.mocked(mockHttpClient.rateLimitedRequest).mock.calls;
      expect(calls).toHaveLength(2);
      expect(calls[1]?.[0]).toBe(`${BASE_URL}/rest/api/content/700/child/attachment?start=25`);
      expect(result?.attachments.map((a) => a.id)).toEqual(['att-1', 'att-2']);
    });
  });
});
