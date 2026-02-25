import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../../config';
import type { ConfluencePage } from '../../confluence-api';
import { ConfluenceApiClient, ContentType } from '../../confluence-api';
import { ConfluenceContentFetcher } from '../confluence-content-fetcher';
import type { DiscoveredPage } from '../sync.types';

const mockTenantLogger = vi.hoisted(() => ({
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

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
    title: `Page ${id}`,
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
    mockTenantLogger as never,
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
    const result = await fetcher.fetchPagesContent([discoveredPage]);

    expect(result).toEqual([
      {
        id: '1',
        title: 'Page 1',
        body: '<p>content</p>',
        webUrl: 'https://confluence.example.com/wiki/1',
        spaceId: 'space-1',
        spaceKey: 'SP',
        spaceName: 'Space',
        metadata: { confluenceLabels: ['engineering'] },
      },
    ]);
    expect(mockTenantLogger.info).toHaveBeenCalledWith(
      { count: 1, total: 1 },
      'Content fetching completed',
    );
  });

  it('omits metadata when page has only ingest labels', async () => {
    const discoveredPage = makeDiscoveredPage('1');
    const apiClient = {
      getPageById: vi
        .fn()
        .mockResolvedValue(makeFullPage('1', { labels: ['ai-ingest', 'ai-ingest-all'] })),
    };

    const fetcher = createFetcher(apiClient);
    const result = await fetcher.fetchPagesContent([discoveredPage]);

    expect(result).toHaveLength(1);
    expect(result[0]?.metadata).toBeUndefined();
  });

  it('skips pages that are missing in Confluence', async () => {
    const discoveredPage = makeDiscoveredPage('missing');
    const apiClient = {
      getPageById: vi.fn().mockResolvedValue(null),
    };

    const fetcher = createFetcher(apiClient);
    const result = await fetcher.fetchPagesContent([discoveredPage]);

    expect(result).toEqual([]);
    expect(mockTenantLogger.warn).toHaveBeenCalledWith(
      { pageId: 'missing', title: 'Page missing' },
      'Page not found, possibly deleted',
    );
  });

  it('skips pages with empty body', async () => {
    const discoveredPage = makeDiscoveredPage('empty');
    const apiClient = {
      getPageById: vi.fn().mockResolvedValue(makeFullPage('empty', { body: '' })),
    };

    const fetcher = createFetcher(apiClient);
    const result = await fetcher.fetchPagesContent([discoveredPage]);

    expect(result).toEqual([]);
    expect(mockTenantLogger.info).toHaveBeenCalledWith(
      { pageId: 'empty', title: 'Page empty' },
      'Page has no body, skipping',
    );
  });

  it('continues processing after getPageById error', async () => {
    const failingPage = makeDiscoveredPage('fail');
    const successfulPage = makeDiscoveredPage('ok');
    const apiClient = {
      getPageById: vi
        .fn()
        .mockRejectedValueOnce(new Error('request failed'))
        .mockResolvedValueOnce(makeFullPage('ok', { labels: ['engineering'] })),
    };

    const fetcher = createFetcher(apiClient);
    const result = await fetcher.fetchPagesContent([failingPage, successfulPage]);

    expect(result.map((page) => page.id)).toEqual(['ok']);
    expect(mockTenantLogger.error).toHaveBeenCalledWith(
      expect.objectContaining({
        pageId: 'fail',
        err: expect.any(Error),
        msg: 'Failed to fetch page, possibly deleted in the meantime',
      }),
    );
  });
});
