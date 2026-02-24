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

const mockBottleneckOn = vi.fn();
const mockBottleneckSchedule = vi.fn(<T>(fn: () => Promise<T>) => fn());

vi.mock('bottleneck', () => ({
  default: class MockBottleneck {
    public on = mockBottleneckOn;
    public schedule = mockBottleneckSchedule;
  },
}));

vi.mock('../../utils/normalize-error', () => ({
  sanitizeError: vi.fn((e: unknown) => e),
}));

import { request } from 'undici';
import type { ConfluenceConfig } from '../../config';
import type { ServiceRegistry } from '../../tenant/service-registry';
import { DataCenterConfluenceApiClient } from '../data-center-api-client';
import type { ConfluencePage } from '../types/confluence-api.types';

const MOCK_TOKEN = 'test-bearer-token';
const BASE_URL = 'https://dc.example.com';

const mockLogger = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
  child: vi.fn(),
};

const mockAuth = { acquireToken: vi.fn().mockResolvedValue(MOCK_TOKEN) };

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

const mockedRequest = request as Mock;

describe('ConfluenceApiClient (base class behavior)', () => {
  let client: DataCenterConfluenceApiClient;

  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.acquireToken.mockResolvedValue(MOCK_TOKEN);
    client = new DataCenterConfluenceApiClient(mockConfig, mockServiceRegistry);
  });

  describe('auth header injection', () => {
    it('includes Authorization Bearer header on every request', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, makePage()));

      await client.getPageById('1');

      expect(mockedRequest).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: { Authorization: `Bearer ${MOCK_TOKEN}` },
        }),
      );
    });

    it('acquires a fresh token before each request', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, makePage({ id: '1', title: 'P' })),
      );
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, makePage({ id: '2', title: 'Q' })),
      );

      await client.getPageById('1');
      await client.getPageById('2');

      expect(mockAuth.acquireToken).toHaveBeenCalledTimes(2);
    });
  });

  describe('rate limit header logging', () => {
    it('logs when x-ratelimit-remaining header is present', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, makePage(), {
          'x-ratelimit-remaining': '42',
        }),
      );

      await client.getPageById('1');

      expect(mockLogger.info).toHaveBeenCalledWith(
        expect.objectContaining({
          msg: 'Confluence rate limit headers',
          'x-ratelimit-remaining': '42',
        }),
      );
    });

    it('logs when x-ratelimit-limit header is present', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, makePage(), {
          'x-ratelimit-limit': '100',
        }),
      );

      await client.getPageById('1');

      expect(mockLogger.info).toHaveBeenCalledWith(
        expect.objectContaining({
          msg: 'Confluence rate limit headers',
          'x-ratelimit-limit': '100',
        }),
      );
    });

    it('does not log rate limit info when headers are absent', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, makePage()));

      await client.getPageById('1');

      expect(mockLogger.info).not.toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Confluence rate limit headers' }),
      );
    });
  });

  describe('HTTP error handling', () => {
    it('throws on non-2xx status codes', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(403, 'Forbidden'));

      await expect(client.getPageById('1')).rejects.toThrow(/Error response from/);
    });

    it('includes status code and URL in error message', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(500, 'Server Error'));

      await expect(client.getPageById('1')).rejects.toThrow(/500/);
    });
  });

  describe('throttle monitoring', () => {
    it('registers depleted, dropped, and error event handlers', () => {
      const registeredEvents = mockBottleneckOn.mock.calls.map((call) => call[0]);
      expect(registeredEvents).toContain('depleted');
      expect(registeredEvents).toContain('dropped');
      expect(registeredEvents).toContain('error');
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

      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, page1));
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, page2));

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

      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, singlePage));

      const results = await client.searchPagesByLabel();

      expect(results).toHaveLength(1);
      expect(mockedRequest).toHaveBeenCalledTimes(1);
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

      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, page1));
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, page2));

      await client.searchPagesByLabel();

      expect(mockedRequest).toHaveBeenCalledTimes(2);
      const secondCall = mockedRequest.mock.calls[1];
      expect(secondCall).toBeDefined();
      const secondCallUrl = secondCall?.[0] as string;
      expect(secondCallUrl).toBe(`${BASE_URL}${nextPath}`);
    });
  });
});
