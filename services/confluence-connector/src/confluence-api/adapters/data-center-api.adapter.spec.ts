import { describe, expect, it, vi } from 'vitest';
import type { ConfluencePage, PaginatedResponse } from '../types/confluence-api.types';
import { ContentType } from '../types/confluence-api.types';
import { DataCenterApiAdapter } from './data-center-api.adapter';

const BASE_URL = 'https://confluence.example.com';

const makePage = (id: string): ConfluencePage => ({
  id,
  title: `Page ${id}`,
  type: ContentType.PAGE,
  space: { id: 'SP1', key: 'SP', name: 'Space' },
  version: { when: '2024-01-01T00:00:00.000Z' },
  _links: { webui: `/pages/viewpage.action?pageId=${id}` },
  metadata: { labels: { results: [] } },
});

type HttpGet = <T>(url: string) => Promise<T>;

describe('DataCenterApiAdapter', () => {
  const adapter = new DataCenterApiAdapter(BASE_URL);

  describe('buildSearchUrl', () => {
    it('builds a search URL with os_authType=basic', () => {
      const url = adapter.buildSearchUrl('space=SP', 25, 0);
      expect(url).toBe(
        'https://confluence.example.com/rest/api/content/search?cql=space%3DSP&expand=metadata.labels,version,space&os_authType=basic&limit=25&start=0',
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
    it('builds a get-page URL with os_authType=basic', () => {
      const url = adapter.buildGetPageUrl('12345');
      expect(url).toBe(
        'https://confluence.example.com/rest/api/content/12345?os_authType=basic&expand=body.storage,version,space,metadata.labels',
      );
    });
  });

  describe('parseSinglePageResponse', () => {
    it('returns the page when body has a string id', () => {
      const page = makePage('42');
      expect(adapter.parseSinglePageResponse(page)).toBe(page);
    });

    it('returns null for null', () => {
      expect(adapter.parseSinglePageResponse(null)).toBeNull();
    });

    it('returns null for non-object values', () => {
      expect(adapter.parseSinglePageResponse('string')).toBeNull();
      expect(adapter.parseSinglePageResponse(123)).toBeNull();
    });

    it('returns null when body has no id property', () => {
      expect(adapter.parseSinglePageResponse({ title: 'No id' })).toBeNull();
    });

    it('returns null when id is not a string', () => {
      expect(adapter.parseSinglePageResponse({ id: 42 })).toBeNull();
    });
  });

  describe('buildPageWebUrl', () => {
    it('builds the canonical page URL using pageId', () => {
      const url = adapter.buildPageWebUrl(makePage('777'));
      expect(url).toBe('https://confluence.example.com/pages/viewpage.action?pageId=777');
    });
  });

  describe('fetchChildPages', () => {
    it('returns pages from a single-page response', async () => {
      const page = makePage('1');
      const response: PaginatedResponse<ConfluencePage> = { results: [page], _links: {} };
      const httpGet = vi.fn().mockResolvedValue(response) as unknown as HttpGet;

      const result = await adapter.fetchChildPages('parent-1', ContentType.PAGE, httpGet);

      expect(result).toEqual([page]);
      expect(httpGet).toHaveBeenCalledOnce();
      expect(httpGet).toHaveBeenCalledWith(
        'https://confluence.example.com/rest/api/content/parent-1/child/page?os_authType=basic&expand=metadata.labels,version,space&limit=50',
      );
    });

    it('paginates until _links.next is absent', async () => {
      const page1 = makePage('1');
      const page2 = makePage('2');
      const httpGet = vi
        .fn()
        .mockResolvedValueOnce({
          results: [page1],
          _links: { next: '/rest/api/content/parent-1/child/page?start=1' },
        } satisfies PaginatedResponse<ConfluencePage>)
        .mockResolvedValueOnce({
          results: [page2],
          _links: {},
        } satisfies PaginatedResponse<ConfluencePage>) as unknown as HttpGet;

      const result = await adapter.fetchChildPages('parent-1', ContentType.PAGE, httpGet);

      expect(result).toEqual([page1, page2]);
      expect(httpGet).toHaveBeenCalledTimes(2);
      expect(httpGet).toHaveBeenNthCalledWith(
        2,
        'https://confluence.example.com/rest/api/content/parent-1/child/page?start=1',
      );
    });

    it('returns an empty array when there are no child pages', async () => {
      const httpGet = vi.fn().mockResolvedValue({
        results: [],
        _links: {},
      } satisfies PaginatedResponse<ConfluencePage>) as unknown as HttpGet;

      const result = await adapter.fetchChildPages('parent-1', ContentType.PAGE, httpGet);

      expect(result).toEqual([]);
    });

    it('uses the same endpoint regardless of contentType', async () => {
      const httpGet = vi.fn().mockResolvedValue({
        results: [],
        _links: {},
      } satisfies PaginatedResponse<ConfluencePage>) as unknown as HttpGet;

      await adapter.fetchChildPages('parent-1', ContentType.FOLDER, httpGet);
      await adapter.fetchChildPages('parent-1', ContentType.DATABASE, httpGet);

      const expectedUrl =
        'https://confluence.example.com/rest/api/content/parent-1/child/page?os_authType=basic&expand=metadata.labels,version,space&limit=50';
      expect(httpGet).toHaveBeenNthCalledWith(1, expectedUrl);
      expect(httpGet).toHaveBeenNthCalledWith(2, expectedUrl);
    });
  });
});
