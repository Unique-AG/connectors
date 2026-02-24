import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig, ProcessingConfig } from '../config';
import type { ConfluencePage } from '../confluence-api';
import { ConfluenceApiClient, ContentType } from '../confluence-api';
import { ConfluencePageScanner } from './confluence-page-scanner';

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

const baseProcessingConfig: ProcessingConfig = {
  stepTimeoutSeconds: 30,
  concurrency: 1,
  scanIntervalCron: '*/5 * * * *',
};

function makePage(
  id: string,
  options: {
    type?: ContentType;
    labels?: string[];
    title?: string;
  } = {},
): ConfluencePage {
  return {
    id,
    title: options.title ?? `Page ${id}`,
    type: options.type ?? ContentType.PAGE,
    space: { id: 'space-1', key: 'SP', name: 'Space' },
    version: { when: '2026-02-01T00:00:00.000Z' },
    _links: { webui: `/wiki/page/${id}` },
    metadata: {
      labels: {
        results: (options.labels ?? []).map((name) => ({ name })),
      },
    },
  };
}

function createScanner(
  apiClient: Pick<ConfluenceApiClient, 'searchPagesByLabel' | 'getChildPages' | 'buildPageWebUrl'>,
  processingConfig: ProcessingConfig = baseProcessingConfig,
): ConfluencePageScanner {
  return new ConfluencePageScanner(
    baseConfluenceConfig,
    processingConfig,
    apiClient as unknown as ConfluenceApiClient,
    mockTenantLogger as never,
  );
}

describe('ConfluencePageScanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('discovers labeled pages and recursively expands ingest-all children', async () => {
    const parent = makePage('parent', { labels: ['ai-ingest-all'] });
    const child = makePage('child', { labels: ['engineering'] });
    const standalone = makePage('standalone', { labels: ['ai-ingest'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([parent, standalone]),
      getChildPages: vi.fn().mockImplementation(async (parentId: string) => {
        if (parentId === 'parent') {
          return [child];
        }
        return [];
      }),
      buildPageWebUrl: vi.fn(
        (page: ConfluencePage) => `https://confluence.example.com/wiki/${page.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.map((page) => page.id)).toEqual(['parent', 'child', 'standalone']);
    expect(apiClient.getChildPages).toHaveBeenCalledWith('parent', ContentType.PAGE);
    expect(apiClient.getChildPages).toHaveBeenCalledWith('child', ContentType.PAGE);
  });

  it('skips database pages', async () => {
    const database = makePage('db-root', {
      type: ContentType.DATABASE,
      labels: ['ai-ingest-all'],
    });
    const page = makePage('page-root', { labels: ['ai-ingest'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([database, page]),
      getChildPages: vi.fn().mockResolvedValue([]),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.map((item) => item.id)).toEqual(['page-root']);
    expect(apiClient.getChildPages).not.toHaveBeenCalled();
  });

  it('respects maxPagesToScan limit', async () => {
    const first = makePage('first', { labels: ['ai-ingest'] });
    const second = makePage('second', { labels: ['ai-ingest'] });
    const limitedConfig: ProcessingConfig = {
      ...baseProcessingConfig,
      maxPagesToScan: 1,
    };

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([first, second]),
      getChildPages: vi.fn().mockResolvedValue([]),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient, limitedConfig);
    const result = await scanner.discoverPages();

    expect(result.map((item) => item.id)).toEqual(['first']);
    expect(mockTenantLogger.info).toHaveBeenCalledWith(
      { limit: 1 },
      'maxPagesToScan limit reached',
    );
  });

  it('returns empty array and logs completion when searchPagesByLabel returns no pages', async () => {
    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([]),
      getChildPages: vi.fn().mockResolvedValue([]),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result).toEqual([]);
    expect(apiClient.getChildPages).not.toHaveBeenCalled();
    expect(mockTenantLogger.info).toHaveBeenCalledWith({ count: 0 }, 'Page discovery completed');
  });

  it('rejects when searchPagesByLabel fails', async () => {
    const apiClient = {
      searchPagesByLabel: vi.fn().mockRejectedValue(new Error('search API error')),
      getChildPages: vi.fn().mockResolvedValue([]),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient);

    await expect(scanner.discoverPages()).rejects.toThrow('search API error');
  });

  it('excludes database child when parent has ingest-all', async () => {
    const parent = makePage('parent', { labels: ['ai-ingest-all'] });
    const databaseChild = makePage('db-child', {
      type: ContentType.DATABASE,
      labels: ['ai-ingest-all'],
    });
    const pageChild = makePage('page-child', { labels: ['engineering'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([parent]),
      getChildPages: vi.fn().mockImplementation(async (parentId: string) => {
        if (parentId === 'parent') {
          return [databaseChild, pageChild];
        }
        return [];
      }),
      buildPageWebUrl: vi.fn(
        (page: ConfluencePage) => `https://confluence.example.com/wiki/${page.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.map((page) => page.id)).toEqual(['parent', 'page-child']);
    expect(mockTenantLogger.info).toHaveBeenCalledWith(
      { pageId: 'db-child', title: 'Page db-child', type: 'database' },
      'Skipping non-page content type',
    );
  });

  it('honors maxPagesToScan limit during child expansion', async () => {
    const parent = makePage('parent', { labels: ['ai-ingest-all'] });
    const child = makePage('child', { labels: ['ai-ingest-all'] });
    const grandchild = makePage('grandchild', { labels: ['engineering'] });
    const limitedConfig: ProcessingConfig = {
      ...baseProcessingConfig,
      maxPagesToScan: 2,
    };

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([parent]),
      getChildPages: vi.fn().mockImplementation(async (parentId: string) => {
        if (parentId === 'parent') return [child];
        if (parentId === 'child') return [grandchild];
        return [];
      }),
      buildPageWebUrl: vi.fn(
        (page: ConfluencePage) => `https://confluence.example.com/wiki/${page.id}`,
      ),
    };

    const scanner = createScanner(apiClient, limitedConfig);
    const result = await scanner.discoverPages();

    expect(result.map((page) => page.id)).toEqual(['parent', 'child']);
    expect(mockTenantLogger.info).toHaveBeenCalledWith(
      { limit: 2 },
      'maxPagesToScan limit reached',
    );
  });

  it('deduplicates pages that appear in both the CQL scan and child expansion', async () => {
    const parent = makePage('parent', { labels: ['ai-ingest-all'] });
    const labeledChild = makePage('labeled-child', { labels: ['ai-ingest'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([parent, labeledChild]),
      getChildPages: vi.fn().mockImplementation(async (parentId: string) => {
        if (parentId === 'parent') return [labeledChild];
        return [];
      }),
      buildPageWebUrl: vi.fn(
        (page: ConfluencePage) => `https://confluence.example.com/wiki/${page.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.map((page) => page.id)).toEqual(['parent', 'labeled-child']);
  });

  it('continues discovery when child fetching fails for one parent', async () => {
    const failingParent = makePage('failing-parent', { labels: ['ai-ingest-all'] });
    const healthyPage = makePage('healthy-page', { labels: ['ai-ingest'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([failingParent, healthyPage]),
      getChildPages: vi.fn().mockRejectedValue(new Error('child lookup failed')),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.map((item) => item.id)).toEqual(['failing-parent', 'healthy-page']);
    expect(mockTenantLogger.warn).toHaveBeenCalledWith(
      expect.objectContaining({ parentId: 'failing-parent', error: expect.anything() }),
      'Failed to fetch child pages, skipping children',
    );
  });
});
