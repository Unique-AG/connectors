import type { Dispatcher } from 'undici';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../config';
import type { ServiceRegistry } from '../tenant/service-registry';
import type { ConfluenceApiAdapter } from './confluence-api-adapter';
import { ConfluenceApiClient } from './confluence-api-client';
import {
  type ConfluencePage,
  ContentType,
  type PaginatedResponse,
} from './types/confluence-api.types';

vi.mock('undici', () => ({
  Agent: class MockAgent {
    public compose() {
      return {};
    }
  },
  interceptors: { redirect: () => ({}), retry: () => ({}) },
  request: vi.fn(),
}));

vi.mock('bottleneck', () => {
  return {
    default: class MockBottleneck {
      public on = vi.fn();
      public schedule = vi.fn(<T>(fn: () => Promise<T>) => fn());
    },
  };
});

import { request } from 'undici';

const BASE_URL = 'https://confluence.example.com';

const makePage = (id: string): ConfluencePage => ({
  id,
  title: `Page ${id}`,
  type: ContentType.PAGE,
  space: { id: 'SP1', key: 'SP', name: 'Space' },
  version: { when: '2024-01-01T00:00:00.000Z' },
  _links: { webui: `/pages/${id}` },
  metadata: { labels: { results: [] } },
});

const makeConfig = (overrides: Partial<ConfluenceConfig> = {}): ConfluenceConfig =>
  ({
    instanceType: 'data-center',
    baseUrl: BASE_URL,
    apiRateLimitPerMinute: 100,
    ingestSingleLabel: 'ai-ingest',
    ingestAllLabel: 'ai-ingest-all',
    auth: { mode: 'pat', token: { expose: () => 'secret' } },
    ...overrides,
  }) as ConfluenceConfig;

const mockLogger = {
  warn: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  debug: vi.fn(),
  child: vi.fn(),
};

const makeServiceRegistry = (): ServiceRegistry =>
  ({
    getService: vi.fn().mockReturnValue({ acquireToken: vi.fn().mockResolvedValue('test-token') }),
    getServiceLogger: vi.fn().mockReturnValue(mockLogger),
  }) as unknown as ServiceRegistry;

const makeAdapter = (overrides: Partial<ConfluenceApiAdapter> = {}): ConfluenceApiAdapter => ({
  buildSearchUrl: vi.fn(
    (cql: string, limit: number, start: number) =>
      `${BASE_URL}/rest/api/content/search?cql=${encodeURIComponent(cql)}&limit=${limit}&start=${start}`,
  ),
  buildGetPageUrl: vi.fn((pageId: string) => `${BASE_URL}/rest/api/content/${pageId}`),
  parseSinglePageResponse: vi.fn((body: unknown) => body as ConfluencePage | null),
  buildPageWebUrl: vi.fn(),
  fetchChildPages: vi.fn().mockResolvedValue([]),
  ...overrides,
});

function mockUndiciResponse(
  statusCode: number,
  body: unknown,
  headers: Record<string, string> = {},
): Dispatcher.ResponseData {
  return {
    statusCode,
    headers,
    body: {
      json: vi.fn().mockResolvedValue(body),
      text: vi.fn().mockResolvedValue(JSON.stringify(body)),
    },
  } as unknown as Dispatcher.ResponseData;
}

describe('ConfluenceApiClient', () => {
  let client: ConfluenceApiClient;
  let adapter: ConfluenceApiAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = makeAdapter();
    client = new ConfluenceApiClient(adapter, makeConfig(), makeServiceRegistry());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('searchPagesByLabel', () => {
    it('returns all pages from a single-page response', async () => {
      const page = makePage('1');
      const response: PaginatedResponse<ConfluencePage> = { results: [page], _links: {} };
      vi.mocked(request).mockResolvedValueOnce(mockUndiciResponse(200, response));

      const result = await client.searchPagesByLabel();

      expect(result).toEqual([page]);
      expect(request).toHaveBeenCalledOnce();
      expect(request).toHaveBeenCalledWith(
        expect.stringContaining('/rest/api/content/search?cql='),
        expect.objectContaining({
          method: 'GET',
          headers: { Authorization: 'Bearer test-token' },
          dispatcher: expect.any(Object),
        }),
      );
    });

    it('paginates until no next link', async () => {
      const page1 = makePage('1');
      const page2 = makePage('2');
      vi.mocked(request)
        .mockResolvedValueOnce(
          mockUndiciResponse(200, {
            results: [page1],
            _links: { next: '/rest/api/content/search?cql=test&start=25' },
          }),
        )
        .mockResolvedValueOnce(mockUndiciResponse(200, { results: [page2], _links: {} }));

      const result = await client.searchPagesByLabel();

      expect(result).toEqual([page1, page2]);
      expect(request).toHaveBeenCalledTimes(2);
    });

    it('constructs CQL with both labels', async () => {
      vi.mocked(request).mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [], _links: {} }),
      );

      await client.searchPagesByLabel();

      expect(adapter.buildSearchUrl).toHaveBeenCalledWith(
        expect.stringContaining('ai-ingest'),
        25,
        0,
      );
      expect(adapter.buildSearchUrl).toHaveBeenCalledWith(
        expect.stringContaining('ai-ingest-all'),
        25,
        0,
      );
    });

    it('uses only global spaces for data-center', async () => {
      client = new ConfluenceApiClient(
        adapter,
        makeConfig({ instanceType: 'data-center' }),
        makeServiceRegistry(),
      );
      vi.mocked(request).mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [], _links: {} }),
      );

      await client.searchPagesByLabel();

      expect(adapter.buildSearchUrl).toHaveBeenCalledWith(
        expect.stringContaining('space.type=global'),
        25,
        0,
      );
      expect(adapter.buildSearchUrl).not.toHaveBeenCalledWith(
        expect.stringContaining('space.type=collaboration'),
        25,
        0,
      );
    });

    it('includes collaboration spaces for cloud', async () => {
      client = new ConfluenceApiClient(
        adapter,
        makeConfig({ instanceType: 'cloud' }),
        makeServiceRegistry(),
      );
      vi.mocked(request).mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [], _links: {} }),
      );

      await client.searchPagesByLabel();

      expect(adapter.buildSearchUrl).toHaveBeenCalledWith(
        expect.stringContaining('space.type=collaboration'),
        25,
        0,
      );
    });
  });

  describe('getPageById', () => {
    it('returns a page when found', async () => {
      const page = makePage('42');
      vi.mocked(request).mockResolvedValueOnce(mockUndiciResponse(200, page));

      const result = await client.getPageById('42');

      expect(result).toEqual(page);
      expect(adapter.buildGetPageUrl).toHaveBeenCalledWith('42');
      expect(adapter.parseSinglePageResponse).toHaveBeenCalledWith(page);
    });

    it('returns null when adapter parses no page', async () => {
      vi.mocked(adapter.parseSinglePageResponse).mockReturnValue(null);
      vi.mocked(request).mockResolvedValueOnce(mockUndiciResponse(200, { results: [] }));

      const result = await client.getPageById('nonexistent');

      expect(result).toBeNull();
    });

    it('throws on HTTP error', async () => {
      vi.mocked(request).mockResolvedValueOnce(mockUndiciResponse(500, 'Internal Server Error'));

      await expect(client.getPageById('42')).rejects.toThrow('Error response from');
    });
  });

  describe('getChildPages', () => {
    it('delegates to adapter.fetchChildPages', async () => {
      const pages = [makePage('c1'), makePage('c2')];
      vi.mocked(adapter.fetchChildPages).mockResolvedValue(pages);

      const result = await client.getChildPages('parent-1', ContentType.PAGE);

      expect(result).toEqual(pages);
      expect(adapter.fetchChildPages).toHaveBeenCalledWith(
        'parent-1',
        ContentType.PAGE,
        expect.any(Function),
      );
    });

    it('passes the rate-limited httpGet to the adapter', async () => {
      const page = makePage('c1');
      vi.mocked(adapter.fetchChildPages).mockImplementation(
        async (_parentId, _contentType, httpGet) => {
          vi.mocked(request).mockResolvedValueOnce(mockUndiciResponse(200, page));
          const result = await httpGet<ConfluencePage>('https://confluence.example.com/test');
          return [result];
        },
      );

      const result = await client.getChildPages('parent-1', ContentType.PAGE);

      expect(result).toEqual([page]);
      expect(request).toHaveBeenCalledWith(
        'https://confluence.example.com/test',
        expect.objectContaining({
          headers: { Authorization: 'Bearer test-token' },
          dispatcher: expect.any(Object),
        }),
      );
    });
  });

  describe('rate limit header logging', () => {
    it('logs rate limit headers when present', async () => {
      vi.mocked(request).mockResolvedValueOnce(
        mockUndiciResponse(
          200,
          { results: [], _links: {} },
          { 'x-ratelimit-remaining': '50', 'x-ratelimit-limit': '100' },
        ),
      );

      await client.searchPagesByLabel();

      expect(mockLogger.info).toHaveBeenCalledWith(
        expect.objectContaining({
          msg: 'Confluence rate limit headers',
          'x-ratelimit-remaining': '50',
          'x-ratelimit-limit': '100',
        }),
      );
    });

    it('does not log when rate limit headers are absent', async () => {
      vi.mocked(request).mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [], _links: {} }),
      );

      await client.searchPagesByLabel();

      expect(mockLogger.warn).not.toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Confluence rate limit headers' }),
      );
    });
  });

  describe('auth header injection', () => {
    it('includes Bearer token in every request', async () => {
      vi.mocked(request).mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [], _links: {} }),
      );

      await client.searchPagesByLabel();

      expect(request).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: { Authorization: 'Bearer test-token' },
          dispatcher: expect.any(Object),
        }),
      );
    });
  });
});
