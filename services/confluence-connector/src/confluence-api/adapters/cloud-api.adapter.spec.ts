import { describe, expect, it, vi } from 'vitest';
import type { ConfluencePage, PaginatedResponse } from '../types/confluence-api.types';
import { ContentType } from '../types/confluence-api.types';
import { CloudApiAdapter } from './cloud-api.adapter';

const API_BASE_URL = 'https://api.atlassian.com/ex/confluence/cloud-id-123';
const SITE_BASE_URL = 'https://mysite.atlassian.net';

const makePage = (id: string): ConfluencePage => ({
  id,
  title: `Page ${id}`,
  type: ContentType.PAGE,
  space: { id: 'SP1', key: 'SP', name: 'Space' },
  version: { when: '2024-01-01T00:00:00.000Z' },
  _links: { webui: `/spaces/SP/pages/${id}/Page+${id}` },
  metadata: { labels: { results: [] } },
});

type HttpGet = <T>(url: string) => Promise<T>;

describe('CloudApiAdapter', () => {
  const adapter = new CloudApiAdapter(API_BASE_URL, SITE_BASE_URL);

  describe('buildSearchUrl', () => {
    it('builds a search URL without os_authType', () => {
      const url = adapter.buildSearchUrl('space=SP', 25, 0);
      expect(url).toBe(
        'https://api.atlassian.com/ex/confluence/cloud-id-123/wiki/rest/api/content/search?cql=space%3DSP&expand=metadata.labels,version,space&limit=25&start=0',
      );
    });

    it('applies limit and start correctly', () => {
      const url = adapter.buildSearchUrl('type=page', 10, 50);
      expect(url).toContain('limit=10');
      expect(url).toContain('start=50');
    });

    it('URL-encodes CQL with spaces and special characters', () => {
      const url = adapter.buildSearchUrl('label="ai-ingest" AND space.type=global', 25, 0);
      expect(url).toContain('cql=label%3D%22ai-ingest%22%20AND%20space.type%3Dglobal');
    });
  });

  describe('buildGetPageUrl', () => {
    it('builds a CQL search URL for the given page id', () => {
      const url = adapter.buildGetPageUrl('12345');
      expect(url).toBe(
        'https://api.atlassian.com/ex/confluence/cloud-id-123/wiki/rest/api/content/search?cql=id%3D12345&expand=body.storage,version,space,metadata.labels',
      );
    });
  });

  describe('parseSinglePageResponse', () => {
    it('returns the first result from a search response', () => {
      const page = makePage('42');
      const body: PaginatedResponse<ConfluencePage> = { results: [page], _links: {} };
      expect(adapter.parseSinglePageResponse(body)).toBe(page);
    });

    it('returns null for null', () => {
      expect(adapter.parseSinglePageResponse(null)).toBeNull();
    });

    it('returns null for non-object values', () => {
      expect(adapter.parseSinglePageResponse('string')).toBeNull();
      expect(adapter.parseSinglePageResponse(123)).toBeNull();
    });

    it('returns null when results is not an array', () => {
      expect(adapter.parseSinglePageResponse({ results: 'not-array' })).toBeNull();
    });

    it('returns null when results is empty', () => {
      expect(adapter.parseSinglePageResponse({ results: [] })).toBeNull();
    });

    it('returns null when first result has no string id', () => {
      expect(adapter.parseSinglePageResponse({ results: [{ id: 42 }] })).toBeNull();
    });
  });

  describe('buildPageWebUrl', () => {
    it('builds the canonical Cloud URL using _links.webui', () => {
      const page = makePage('777');
      const url = adapter.buildPageWebUrl(page);
      expect(url).toBe('https://mysite.atlassian.net/wiki/spaces/SP/pages/777/Page+777');
    });
  });

  describe('fetchChildPages', () => {
    it('uses the pages V2 endpoint for page content type', async () => {
      const child = makePage('c1');
      const httpGet = vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: 'c1' }], _links: {} })
        .mockResolvedValueOnce({ results: [child], _links: {} }) as unknown as HttpGet;

      const result = await adapter.fetchChildPages('parent-1', ContentType.PAGE, httpGet);

      expect(result).toEqual([child]);
      expect(httpGet).toHaveBeenCalledWith(
        'https://api.atlassian.com/ex/confluence/cloud-id-123/wiki/api/v2/pages/parent-1/direct-children?limit=250',
      );
      expect(httpGet).toHaveBeenCalledWith(
        'https://api.atlassian.com/ex/confluence/cloud-id-123/wiki/rest/api/content/search?cql=id%3Dc1&expand=metadata.labels,version,space',
      );
    });

    it('uses the folders V2 endpoint for folder content type', async () => {
      const httpGet = vi
        .fn()
        .mockResolvedValueOnce({ results: [], _links: {} }) as unknown as HttpGet;

      await adapter.fetchChildPages('parent-1', ContentType.FOLDER, httpGet);

      expect(httpGet).toHaveBeenCalledWith(
        'https://api.atlassian.com/ex/confluence/cloud-id-123/wiki/api/v2/folders/parent-1/direct-children?limit=250',
      );
    });

    it('uses the databases V2 endpoint for database content type', async () => {
      const httpGet = vi
        .fn()
        .mockResolvedValueOnce({ results: [], _links: {} }) as unknown as HttpGet;

      await adapter.fetchChildPages('parent-1', ContentType.DATABASE, httpGet);

      expect(httpGet).toHaveBeenCalledWith(
        'https://api.atlassian.com/ex/confluence/cloud-id-123/wiki/api/v2/databases/parent-1/direct-children?limit=250',
      );
    });

    it('fetches detail for each child via N+1 CQL requests', async () => {
      const child1 = makePage('c1');
      const child2 = makePage('c2');
      const httpGet = vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: 'c1' }, { id: 'c2' }], _links: {} })
        .mockResolvedValueOnce({ results: [child1], _links: {} })
        .mockResolvedValueOnce({ results: [child2], _links: {} }) as unknown as HttpGet;

      const result = await adapter.fetchChildPages('parent-1', ContentType.PAGE, httpGet);

      expect(result).toEqual([child1, child2]);
      expect(httpGet).toHaveBeenCalledTimes(3);
    });

    it('skips children whose detail fetch returns empty results', async () => {
      const child1 = makePage('c1');
      const httpGet = vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: 'c1' }, { id: 'c2' }], _links: {} })
        .mockResolvedValueOnce({ results: [child1], _links: {} })
        .mockResolvedValueOnce({ results: [], _links: {} }) as unknown as HttpGet;

      const result = await adapter.fetchChildPages('parent-1', ContentType.PAGE, httpGet);

      expect(result).toEqual([child1]);
    });

    it('returns an empty array when there are no children', async () => {
      const httpGet = vi
        .fn()
        .mockResolvedValueOnce({ results: [], _links: {} }) as unknown as HttpGet;

      const result = await adapter.fetchChildPages('parent-1', ContentType.PAGE, httpGet);

      expect(result).toEqual([]);
      expect(httpGet).toHaveBeenCalledOnce();
    });

    it('paginates the V2 direct-children endpoint', async () => {
      const child1 = makePage('c1');
      const child2 = makePage('c2');
      const httpGet = vi
        .fn()
        .mockResolvedValueOnce({
          results: [{ id: 'c1' }],
          _links: { next: '/wiki/api/v2/pages/parent-1/direct-children?cursor=abc' },
        })
        .mockResolvedValueOnce({
          results: [{ id: 'c2' }],
          _links: {},
        })
        .mockResolvedValueOnce({ results: [child1], _links: {} })
        .mockResolvedValueOnce({ results: [child2], _links: {} }) as unknown as HttpGet;

      const result = await adapter.fetchChildPages('parent-1', ContentType.PAGE, httpGet);

      expect(result).toEqual([child1, child2]);
      expect(httpGet).toHaveBeenCalledTimes(4);
      expect(httpGet).toHaveBeenNthCalledWith(
        2,
        'https://api.atlassian.com/ex/confluence/cloud-id-123/wiki/api/v2/pages/parent-1/direct-children?cursor=abc',
      );
    });
  });
});
