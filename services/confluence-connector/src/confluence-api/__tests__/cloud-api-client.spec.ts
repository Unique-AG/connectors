import type { Dispatcher } from 'undici';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';

vi.mock('undici', () => ({
  Agent: class MockAgent {
    public compose() {
      return {};
    }
  },
  interceptors: { redirect: () => ({}), retry: () => ({}) },
  request: vi.fn(),
}));

vi.mock('bottleneck', () => ({
  default: class MockBottleneck {
    public on = vi.fn();
    public schedule = vi.fn(<T>(fn: () => Promise<T>) => fn());
  },
}));

vi.mock('../../utils/normalize-error', () => ({
  sanitizeError: vi.fn((e: unknown) => e),
}));

import { request } from 'undici';
import type { ConfluenceConfig } from '../../config';
import type { ServiceRegistry } from '../../tenant/service-registry';
import { CloudConfluenceApiClient } from '../cloud-api-client';
import { type ConfluencePage, ContentType } from '../types/confluence-api.types';

const BASE_URL = 'https://cloud.example.com';

const mockLogger = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
  child: vi.fn(),
};

const mockAuth = { acquireToken: vi.fn().mockResolvedValue('cloud-token') };

const mockServiceRegistry = {
  getService: vi.fn().mockReturnValue(mockAuth),
  getServiceLogger: vi.fn().mockReturnValue(mockLogger),
} as unknown as ServiceRegistry;

const mockConfig: ConfluenceConfig = {
  baseUrl: BASE_URL,
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
  instanceType: 'cloud',
  auth: { mode: 'oauth_2lo', clientId: 'cid', clientSecret: { expose: () => 'sec' } },
} as unknown as ConfluenceConfig;

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

const mockedRequest = request as Mock;

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
    client = new CloudConfluenceApiClient(mockConfig, mockServiceRegistry);
  });

  describe('searchPagesByLabel', () => {
    it('constructs CQL with global and collaboration space type filter', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.searchPagesByLabel();

      const url = mockedRequest.mock.calls[0]![0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('(space.type=global OR space.type=collaboration)');
      expect(decodedUrl).toContain('label="sync"');
      expect(decodedUrl).toContain('label="sync-all"');
      expect(decodedUrl).toContain('type != attachment');
    });

    it('uses /wiki/rest/api/content/search without os_authType', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.searchPagesByLabel();

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('/wiki/rest/api/content/search');
      expect(url).not.toContain('os_authType');
    });

    it('uses limit=25 for search', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.searchPagesByLabel();

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('limit=25');
    });
  });

  describe('getPageById', () => {
    it('uses CQL search endpoint with id filter', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [makePage({ id: '77' })], _links: {} }),
      );

      await client.getPageById('77');

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('/wiki/rest/api/content/search');
      expect(url).toContain('cql=id%3D77');
      expect(url).toContain('expand=body.storage,version,space,metadata.labels');
    });

    it('returns first result from paginated response', async () => {
      const page = makePage({ id: '77', title: 'Found' });
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [page], _links: {} }));

      const result = await client.getPageById('77');

      expect(result).toEqual(page);
    });

    it('returns null for non-object body', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, 'not-an-object'));

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });

    it('returns null for empty results array', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });

    it('returns null when first result has no string id', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [{ id: 123, title: 'Bad' }], _links: {} }),
      );

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });

    it('returns null when body has no results property', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { data: [] }));

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });
  });

  describe('getChildPages', () => {
    it('uses V2 direct-children endpoint for pages', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.getChildPages('10', ContentType.PAGE);

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('/wiki/api/v2/pages/10/direct-children');
      expect(url).toContain('limit=250');
    });

    it('uses V2 direct-children endpoint for folders', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.getChildPages('10', ContentType.FOLDER);

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('/wiki/api/v2/folders/10/direct-children');
    });

    it('uses V2 direct-children endpoint for databases', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.getChildPages('10', ContentType.DATABASE);

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('/wiki/api/v2/databases/10/direct-children');
    });

    it('fetches detail for each child via CQL search', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [{ id: 'c1' }, { id: 'c2' }], _links: {} }),
      );
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [makePage({ id: 'c1' })], _links: {} }),
      );
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [makePage({ id: 'c2' })], _links: {} }),
      );

      const result = await client.getChildPages('10', ContentType.PAGE);

      expect(result).toHaveLength(2);

      const detailUrl1 = mockedRequest.mock.calls[1]![0] as string;
      expect(detailUrl1).toContain('/wiki/rest/api/content/search');
      expect(detailUrl1).toContain('cql=id%3Dc1');

      const detailUrl2 = mockedRequest.mock.calls[2]![0] as string;
      expect(detailUrl2).toContain('cql=id%3Dc2');
    });

    it('skips children whose detail fetch returns empty results', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [{ id: 'c1' }, { id: 'c2' }], _links: {} }),
      );
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [makePage({ id: 'c1' })], _links: {} }),
      );
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      const result = await client.getChildPages('10', ContentType.PAGE);

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('c1');
    });

    it('paginates direct-children endpoint', async () => {
      const nextPath = '/wiki/api/v2/pages/10/direct-children?cursor=abc';
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [{ id: 'c1' }], _links: { next: nextPath } }),
      );
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [{ id: 'c2' }], _links: {} }),
      );
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [makePage({ id: 'c1' })], _links: {} }),
      );
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, { results: [makePage({ id: 'c2' })], _links: {} }),
      );

      const result = await client.getChildPages('10', ContentType.PAGE);

      expect(result).toHaveLength(2);
      const paginatedUrl = mockedRequest.mock.calls[1]![0] as string;
      expect(paginatedUrl).toBe(`${BASE_URL}${nextPath}`);
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
