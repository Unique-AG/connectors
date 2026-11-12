import { Smeared } from '@unique-ag/utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ZodError } from 'zod';
import type { ConfluenceConfig } from '../../config';
import type { ConfluencePage } from '../../confluence-api';
import { ConfluenceApiClient, ContentType } from '../../confluence-api';
import { HttpStatusError } from '../../utils/http-util';
import { ConfluenceContentFetcher } from '../confluence-content-fetcher';
import type { DiscoveredPage } from '../sync.types';

const mockLogger = vi.hoisted(() => ({
  log: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
  verbose: vi.fn(),
}));

vi.mock('@nestjs/common', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nestjs/common')>();
  return {
    ...actual,
    Logger: vi.fn(
      class MockLogger {
        public constructor() {
          Object.assign(this, mockLogger);
        }
      },
    ),
  };
});

const baseConfluenceConfig: ConfluenceConfig = {
  instanceType: 'data-center',
  baseUrl: 'https://confluence.example.com',
  apiRateLimitPerMinute: 250,
  ingestSingleLabel: 'ai-ingest',
  ingestAllLabel: 'ai-ingest-all',
  auth: {
    mode: 'pat',
    token: { expose: () => 'secret' },
  },
} as unknown as ConfluenceConfig;

function makeDiscoveredPage(id: string, overrides: Partial<DiscoveredPage> = {}): DiscoveredPage {
  return {
    id,
    title: new Smeared(`Page ${id}`, false),
    type: ContentType.PAGE,
    spaceId: 'space-1',
    spaceKey: 'SP',
    spaceName: 'Space',
    versionTimestamp: '2026-02-01T00:00:00.000Z',
    webUrl: `https://confluence.example.com/wiki/${id}`,
    labels: ['ai-ingest'],
    ...overrides,
  };
}

function makeFullPage(
  id: string,
  options: {
    body?: string;
    labels?: string[];
  } = {},
): ConfluencePage {
  return {
    id,
    title: `Full ${id}`,
    type: ContentType.PAGE,
    space: { id: 'space-1', key: 'SP', name: 'Space' },
    body:
      options.body === undefined
        ? { storage: { value: '<p>content</p>' } }
        : { storage: { value: options.body } },
    version: { when: '2026-02-01T00:00:00.000Z' },
    _links: { webui: `/wiki/${id}` },
    metadata: {
      labels: {
        results: (options.labels ?? []).map((name) => ({ name })),
      },
    },
  };
}

function createFetcher(
  apiClient: Pick<ConfluenceApiClient, 'getPageById'>,
): ConfluenceContentFetcher {
  return new ConfluenceContentFetcher(
    baseConfluenceConfig,
    apiClient as unknown as ConfluenceApiClient,
  );
}

describe('ConfluenceContentFetcher', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches page content and builds fetched page metadata', async () => {
    const discoveredPage = makeDiscoveredPage('1');
    const apiClient = {
      getPageById: vi
        .fn()
        .mockResolvedValue(
          makeFullPage('1', { labels: ['ai-ingest', 'ai-ingest-all', 'engineering'] }),
        ),
    };

    const fetcher = createFetcher(apiClient);
    const result = await fetcher.fetchPageContent(discoveredPage);

    expect(result).toEqual({
      id: '1',
      title: new Smeared('Page 1', false),
      body: '<p>content</p>',
      webUrl: 'https://confluence.example.com/wiki/1',
      spaceId: 'space-1',
      spaceKey: 'SP',
      spaceName: 'Space',
      metadata: { confluenceLabels: ['engineering'] },
    });
  });

  it('omits metadata when page has only ingest labels', async () => {
    const discoveredPage = makeDiscoveredPage('1');
    const apiClient = {
      getPageById: vi
        .fn()
        .mockResolvedValue(makeFullPage('1', { labels: ['ai-ingest', 'ai-ingest-all'] })),
    };

    const fetcher = createFetcher(apiClient);
    const result = await fetcher.fetchPageContent(discoveredPage);

    expect(result).toBeDefined();
    expect(result?.metadata).toBeUndefined();
  });

  it('skips pages that are missing in Confluence', async () => {
    const discoveredPage = makeDiscoveredPage('missing');
    const apiClient = {
      getPageById: vi.fn().mockResolvedValue(null),
    };

    const fetcher = createFetcher(apiClient);
    const result = await fetcher.fetchPageContent(discoveredPage);

    expect(result).toBeNull();
    expect(mockLogger.warn).toHaveBeenCalledWith({
      pageId: 'missing',
      title: new Smeared('Page missing', false),
      msg: 'Page not found, possibly deleted',
    });
  });

  it('skips pages with empty body', async () => {
    const discoveredPage = makeDiscoveredPage('empty');
    const apiClient = {
      getPageById: vi.fn().mockResolvedValue(makeFullPage('empty', { body: '' })),
    };

    const fetcher = createFetcher(apiClient);
    const result = await fetcher.fetchPageContent(discoveredPage);

    expect(result).toBeNull();
    expect(mockLogger.debug).toHaveBeenCalledWith({
      pageId: 'empty',
      title: new Smeared('Page empty', false),
      msg: 'Page has no body, skipping',
    });
  });

  it('does not fetch an empty page again while its version is unchanged', async () => {
    const discoveredPage = makeDiscoveredPage('empty');
    const apiClient = {
      getPageById: vi.fn().mockResolvedValue(makeFullPage('empty', { body: '' })),
    };

    const fetcher = createFetcher(apiClient);
    await fetcher.fetchPageContent(discoveredPage);
    const result = await fetcher.fetchPageContent(discoveredPage);

    expect(result).toBeNull();
    expect(apiClient.getPageById).toHaveBeenCalledTimes(1);
  });

  it('fetches an empty page again once it has a new version', async () => {
    const apiClient = {
      getPageById: vi
        .fn()
        .mockResolvedValueOnce(makeFullPage('edited', { body: '' }))
        .mockResolvedValueOnce(makeFullPage('edited', { body: '<p>now with content</p>' })),
    };

    const fetcher = createFetcher(apiClient);
    await fetcher.fetchPageContent(makeDiscoveredPage('edited'));
    const result = await fetcher.fetchPageContent(
      makeDiscoveredPage('edited', { versionTimestamp: '2026-03-01T00:00:00.000Z' }),
    );

    expect(result?.body).toBe('<p>now with content</p>');
    expect(apiClient.getPageById).toHaveBeenCalledTimes(2);
  });

  it('returns labels sorted alphabetically', async () => {
    const discoveredPage = makeDiscoveredPage('1');
    const apiClient = {
      getPageById: vi
        .fn()
        .mockResolvedValue(makeFullPage('1', { labels: ['zebra', 'alpha', 'ai-ingest'] })),
    };

    const fetcher = createFetcher(apiClient);
    const result = await fetcher.fetchPageContent(discoveredPage);

    expect(result?.metadata?.confluenceLabels).toEqual(['alpha', 'zebra']);
  });

  it('rethrows a failed request and logs its status code without the response body', async () => {
    const requestError = new HttpStatusError(
      500,
      'Error response from https://confluence.example.com: 500 secret page content',
    );
    const apiClient = { getPageById: vi.fn().mockRejectedValue(requestError) };

    const fetcher = createFetcher(apiClient);

    await expect(fetcher.fetchPageContent(makeDiscoveredPage('fail'))).rejects.toBe(requestError);
    expect(mockLogger.error).toHaveBeenCalledWith({
      pageId: 'fail',
      title: new Smeared('Page fail', false),
      errorName: 'HttpStatusError',
      statusCode: 500,
      msg: 'Failed to fetch page',
    });
  });

  it('rethrows an unexpected response and logs where it failed validation', async () => {
    const validationError = new ZodError([
      {
        code: 'invalid_type',
        expected: 'object',
        path: ['results', 0, 'body', 'storage'],
        message: 'Invalid input: expected object, received undefined',
      },
    ]);
    const apiClient = { getPageById: vi.fn().mockRejectedValue(validationError) };

    const fetcher = createFetcher(apiClient);

    await expect(fetcher.fetchPageContent(makeDiscoveredPage('invalid'))).rejects.toBe(
      validationError,
    );
    expect(mockLogger.error).toHaveBeenCalledWith({
      pageId: 'invalid',
      title: new Smeared('Page invalid', false),
      errorName: 'ZodError',
      issues: [{ code: 'invalid_type', path: 'results.0.body.storage' }],
      msg: 'Failed to fetch page',
    });
  });
});
