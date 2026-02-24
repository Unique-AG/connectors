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
import { DataCenterConfluenceApiClient } from '../data-center-api-client';
import { ContentType } from '../types/confluence-api.types';

const BASE_URL = 'https://dc.example.com';

const mockLogger = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
  child: vi.fn(),
};

const mockAuth = { acquireToken: vi.fn().mockResolvedValue('dc-token') };

const mockServiceRegistry = {
  getService: vi.fn().mockReturnValue(mockAuth),
  getServiceLogger: vi.fn().mockReturnValue(mockLogger),
} as unknown as ServiceRegistry;

const mockConfig: ConfluenceConfig = {
  baseUrl: BASE_URL,
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
  instanceType: 'data-center',
  auth: { mode: 'pat', token: { expose: () => 'tok' } },
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
    client = new DataCenterConfluenceApiClient(mockConfig, mockServiceRegistry);
  });

  describe('searchPagesByLabel', () => {
    it('constructs CQL with both labels and space.type=global filter', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.searchPagesByLabel();

      const url = mockedRequest.mock.calls[0]![0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).toContain('label="sync"');
      expect(decodedUrl).toContain('label="sync-all"');
      expect(decodedUrl).toContain('space.type=global');
      expect(decodedUrl).toContain('type != attachment');
    });

    it('uses /rest/api/content/search with os_authType=basic', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.searchPagesByLabel();

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('/rest/api/content/search');
      expect(url).toContain('os_authType=basic');
    });

    it('excludes collaboration space type from filter', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.searchPagesByLabel();

      const url = mockedRequest.mock.calls[0]![0] as string;
      const decodedUrl = decodeURIComponent(url);
      expect(decodedUrl).not.toContain('collaboration');
    });

    it('uses limit=25 for search pages', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.searchPagesByLabel();

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('limit=25');
    });
  });

  describe('getPageById', () => {
    it('uses direct content endpoint with os_authType=basic', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, makePage({ id: '42' })));

      await client.getPageById('42');

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('/rest/api/content/42');
      expect(url).toContain('os_authType=basic');
      expect(url).toContain('expand=body.storage,version,space,metadata.labels');
    });

    it('returns the page when response has a valid id', async () => {
      const page = makePage({ id: '42' });
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, page));

      const result = await client.getPageById('42');

      expect(result).toEqual(page);
    });

    it('returns null for null response', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, null));

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });

    it('returns null for undefined response', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, undefined));

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });

    it('returns null for non-object response', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, 'not-an-object'));

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });

    it('returns null when id is not a string', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { id: 123, title: 'P' }));

      const result = await client.getPageById('1');

      expect(result).toBeNull();
    });
  });

  describe('getChildPages', () => {
    it('uses V1 /child/page endpoint with os_authType=basic', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.getChildPages('55', ContentType.PAGE);

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('/rest/api/content/55/child/page');
      expect(url).toContain('os_authType=basic');
    });

    it('ignores contentType parameter — always uses /child/page', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.getChildPages('55', ContentType.FOLDER);

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('/child/page');
      expect(url).not.toContain('folders');
    });

    it('uses limit=50 for child pages', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { results: [], _links: {} }));

      await client.getChildPages('55', ContentType.PAGE);

      const url = mockedRequest.mock.calls[0]![0] as string;
      expect(url).toContain('limit=50');
    });

    it('returns paginated child pages', async () => {
      const page1 = {
        results: [makePage({ id: '10' })],
        _links: { next: '/rest/api/content/55/child/page?cursor=x' },
      };
      const page2 = { results: [makePage({ id: '11' })], _links: {} };

      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, page1));
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, page2));

      const results = await client.getChildPages('55', ContentType.PAGE);

      expect(results).toHaveLength(2);
      expect(results[0]!.id).toBe('10');
      expect(results[1]!.id).toBe('11');
    });
  });

  describe('buildPageWebUrl', () => {
    it('builds viewpage URL with page id', () => {
      const page = makePage({ id: '99' });

      const url = client.buildPageWebUrl(page);

      expect(url).toBe(`${BASE_URL}/pages/viewpage.action?pageId=99`);
    });
  });
});
