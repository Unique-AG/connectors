vi.mock('@unique-ag/utils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@unique-ag/utils')>();
  return {
    ...actual,
    createSmeared: (value: string) => new actual.Smeared(value, false),
  };
});

import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig, ProcessingConfig } from '../../config';
import type { AttachmentConfig } from '../../config/ingestion.schema';
import type { ConfluenceAttachment, ConfluencePage } from '../../confluence-api';
import { ConfluenceApiClient, ContentType } from '../../confluence-api';
import { ConfluencePageScanner } from '../confluence-page-scanner';

const mockLogger = vi.hoisted(() => ({
  log: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

vi.mock('@nestjs/common', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nestjs/common')>();
  return {
    ...actual,
    Logger: vi.fn().mockImplementation(() => mockLogger),
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

const baseProcessingConfig: ProcessingConfig = {
  concurrency: 1,
  scanIntervalCron: '*/5 * * * *',
};

const disabledAttachmentConfig: AttachmentConfig = {
  mode: false,
  allowedExtensions: ['pdf', 'docx'],
  maxFileSizeMb: 10,
};

const enabledAttachmentConfig: AttachmentConfig = {
  mode: true,
  allowedExtensions: ['pdf', 'docx'],
  maxFileSizeMb: 10,
};

function makeAttachment(
  id: string,
  title: string,
  overrides: Partial<{
    fileSize: number;
    mediaType: string;
    versionWhen: string;
  }> = {},
): ConfluenceAttachment {
  return {
    id,
    title,
    extensions: {
      mediaType: overrides.mediaType ?? 'application/pdf',
      fileSize: overrides.fileSize ?? 1_000,
    },
    version: overrides.versionWhen ? { when: overrides.versionWhen } : undefined,
    _links: { download: `/download/attachments/${id}/${title}` },
  };
}

function makePage(
  id: string,
  options: {
    type?: ContentType;
    labels?: string[];
    title?: string;
    attachments?: ConfluenceAttachment[];
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
    children: options.attachments ? { attachment: { results: options.attachments } } : undefined,
  };
}

function createScanner(
  apiClient: Pick<
    ConfluenceApiClient,
    'searchPagesByLabel' | 'getDescendantPages' | 'buildPageWebUrl'
  >,
  processingConfig: ProcessingConfig = baseProcessingConfig,
  attachmentConfig: AttachmentConfig = disabledAttachmentConfig,
): ConfluencePageScanner {
  return new ConfluencePageScanner(
    baseConfluenceConfig,
    processingConfig,
    apiClient as unknown as ConfluenceApiClient,
    attachmentConfig,
  );
}

describe('ConfluencePageScanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('discovers labeled pages and expands ingest-all descendants', async () => {
    const parent = makePage('parent', { labels: ['ai-ingest-all'] });
    const child = makePage('child', { labels: ['engineering'] });
    const standalone = makePage('standalone', { labels: ['ai-ingest'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([parent, standalone]),
      getDescendantPages: vi.fn().mockResolvedValue([child]),
      buildPageWebUrl: vi.fn(
        (page: ConfluencePage) => `https://confluence.example.com/wiki/${page.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.pages.map((page) => page.id)).toEqual(['parent', 'standalone', 'child']);
    expect(apiClient.getDescendantPages).toHaveBeenCalledWith(['parent']);
  });

  it('skips database pages from discovery results', async () => {
    const database = makePage('db-root', {
      type: ContentType.DATABASE,
      labels: ['ai-ingest'],
    });
    const page = makePage('page-root', { labels: ['ai-ingest'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([database, page]),
      getDescendantPages: vi.fn().mockResolvedValue([]),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.pages.map((item) => item.id)).toEqual(['page-root']);
    expect(apiClient.getDescendantPages).not.toHaveBeenCalled();
  });

  it('expands descendants EVEN when ai-ingest-all is on a skipped content type', async () => {
    const database = makePage('db-root', {
      type: ContentType.DATABASE,
      labels: ['ai-ingest-all'],
    });
    const child = makePage('child-page', { labels: ['engineering'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([database]),
      getDescendantPages: vi.fn().mockResolvedValue([child]),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.pages.map((item) => item.id)).toEqual(['child-page']);
    expect(apiClient.getDescendantPages).toHaveBeenCalledWith(['db-root']);
  });

  it('respects maxItemsToScan limit', async () => {
    const first = makePage('first', { labels: ['ai-ingest'] });
    const second = makePage('second', { labels: ['ai-ingest'] });
    const limitedConfig: ProcessingConfig = {
      ...baseProcessingConfig,
      maxItemsToScan: 1,
    };

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([first, second]),
      getDescendantPages: vi.fn().mockResolvedValue([]),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient, limitedConfig);
    const result = await scanner.discoverPages();

    expect(result.pages.map((item) => item.id)).toEqual(['first']);
    expect(mockLogger.log).toHaveBeenCalledWith({ limit: 1, msg: 'maxItemsToScan limit reached' });
  });

  it('returns empty pages and attachments when searchPagesByLabel returns no pages', async () => {
    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([]),
      getDescendantPages: vi.fn().mockResolvedValue([]),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.pages).toEqual([]);
    expect(result.attachments).toEqual([]);
    expect(apiClient.getDescendantPages).not.toHaveBeenCalled();
    expect(mockLogger.log).toHaveBeenCalledWith({ count: 0, msg: 'Page discovery completed' });
  });

  it('rejects when searchPagesByLabel fails', async () => {
    const apiClient = {
      searchPagesByLabel: vi.fn().mockRejectedValue(new Error('search API error')),
      getDescendantPages: vi.fn().mockResolvedValue([]),
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
      getDescendantPages: vi.fn().mockResolvedValue([databaseChild, pageChild]),
      buildPageWebUrl: vi.fn(
        (page: ConfluencePage) => `https://confluence.example.com/wiki/${page.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.pages.map((page) => page.id)).toEqual(['parent', 'page-child']);
    expect(mockLogger.debug).toHaveBeenCalledWith(
      expect.objectContaining({
        pageId: 'db-child',
        type: 'database',
        msg: 'Skipping non-page content type',
      }),
    );
  });

  it('honors maxItemsToScan limit during descendant expansion', async () => {
    const parent = makePage('parent', { labels: ['ai-ingest-all'] });
    const child = makePage('child', { labels: ['engineering'] });
    const grandchild = makePage('grandchild', { labels: ['engineering'] });
    const limitedConfig: ProcessingConfig = {
      ...baseProcessingConfig,
      maxItemsToScan: 2,
    };

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([parent]),
      getDescendantPages: vi.fn().mockResolvedValue([child, grandchild]),
      buildPageWebUrl: vi.fn(
        (page: ConfluencePage) => `https://confluence.example.com/wiki/${page.id}`,
      ),
    };

    const scanner = createScanner(apiClient, limitedConfig);
    const result = await scanner.discoverPages();

    expect(result.pages.map((page) => page.id)).toEqual(['parent', 'child']);
    expect(mockLogger.log).toHaveBeenCalledWith({ limit: 2, msg: 'maxItemsToScan limit reached' });
  });

  it('deduplicates pages that appear in both the CQL scan and descendant expansion', async () => {
    const parent = makePage('parent', { labels: ['ai-ingest-all'] });
    const labeledChild = makePage('labeled-child', { labels: ['ai-ingest'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([parent, labeledChild]),
      getDescendantPages: vi.fn().mockResolvedValue([labeledChild]),
      buildPageWebUrl: vi.fn(
        (page: ConfluencePage) => `https://confluence.example.com/wiki/${page.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.pages.map((page) => page.id)).toEqual(['parent', 'labeled-child']);
  });

  it('includes blog posts in discovery results', async () => {
    const blog = makePage('blog-1', {
      type: ContentType.BLOGPOST,
      labels: ['ai-ingest'],
    });
    const page = makePage('page-1', { labels: ['ai-ingest'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([blog, page]),
      getDescendantPages: vi.fn().mockResolvedValue([]),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient);
    const result = await scanner.discoverPages();

    expect(result.pages.map((item) => item.id)).toEqual(['blog-1', 'page-1']);
  });

  it('rejects when descendant fetching fails', async () => {
    const ingestAllPage = makePage('ingest-all-page', { labels: ['ai-ingest-all'] });
    const healthyPage = makePage('healthy-page', { labels: ['ai-ingest'] });

    const apiClient = {
      searchPagesByLabel: vi.fn().mockResolvedValue([ingestAllPage, healthyPage]),
      getDescendantPages: vi.fn().mockRejectedValue(new Error('descendant lookup failed')),
      buildPageWebUrl: vi.fn(
        (item: ConfluencePage) => `https://confluence.example.com/wiki/${item.id}`,
      ),
    };

    const scanner = createScanner(apiClient);

    await expect(scanner.discoverPages()).rejects.toThrow('descendant lookup failed');
  });

  describe('attachment extraction', () => {
    it('extracts attachments from pages when attachments are enabled', async () => {
      const attachment = makeAttachment('att-1', 'report.pdf', {
        versionWhen: '2026-03-01T00:00:00.000Z',
      });
      const page = makePage('page-1', {
        labels: ['ai-ingest'],
        attachments: [attachment],
      });

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([page]),
        getDescendantPages: vi.fn().mockResolvedValue([]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, baseProcessingConfig, enabledAttachmentConfig);
      const result = await scanner.discoverPages();

      expect(result.attachments).toEqual([
        {
          id: 'att-1',
          title: 'report.pdf',
          mediaType: 'application/pdf',
          fileSize: 1_000,
          downloadPath: '/download/attachments/att-1/report.pdf',
          versionTimestamp: '2026-03-01T00:00:00.000Z',
          pageId: 'page-1',
          spaceId: 'space-1',
          spaceKey: 'SP',
          spaceName: 'Space',
          webUrl: 'https://confluence.example.com/wiki/page-1',
        },
      ]);
    });

    it('returns no attachments when attachments are disabled', async () => {
      const attachment = makeAttachment('att-1', 'report.pdf');
      const page = makePage('page-1', {
        labels: ['ai-ingest'],
        attachments: [attachment],
      });

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([page]),
        getDescendantPages: vi.fn().mockResolvedValue([]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, baseProcessingConfig, disabledAttachmentConfig);
      const result = await scanner.discoverPages();

      expect(result.attachments).toEqual([]);
    });

    it('filters out attachments with disallowed extensions', async () => {
      const allowed = makeAttachment('att-1', 'report.pdf');
      const disallowed = makeAttachment('att-2', 'image.png');

      const page = makePage('page-1', {
        labels: ['ai-ingest'],
        attachments: [allowed, disallowed],
      });

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([page]),
        getDescendantPages: vi.fn().mockResolvedValue([]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, baseProcessingConfig, enabledAttachmentConfig);
      const result = await scanner.discoverPages();

      expect(result.attachments.map((a) => a.id)).toEqual(['att-1']);
    });

    it('filters out attachments exceeding max file size', async () => {
      const small = makeAttachment('att-1', 'small.pdf', { fileSize: 1_000 });
      const large = makeAttachment('att-2', 'large.pdf', { fileSize: 50_000_000 });

      const page = makePage('page-1', {
        labels: ['ai-ingest'],
        attachments: [small, large],
      });

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([page]),
        getDescendantPages: vi.fn().mockResolvedValue([]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, baseProcessingConfig, enabledAttachmentConfig);
      const result = await scanner.discoverPages();

      expect(result.attachments.map((a) => a.id)).toEqual(['att-1']);
    });

    it('filters out attachments with no file extension', async () => {
      const noExt = makeAttachment('att-1', 'README');
      const page = makePage('page-1', {
        labels: ['ai-ingest'],
        attachments: [noExt],
      });

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([page]),
        getDescendantPages: vi.fn().mockResolvedValue([]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, baseProcessingConfig, enabledAttachmentConfig);
      const result = await scanner.discoverPages();

      expect(result.attachments).toEqual([]);
    });

    it('handles attachments with undefined version timestamp', async () => {
      const attachment = makeAttachment('att-1', 'report.pdf');

      const page = makePage('page-1', {
        labels: ['ai-ingest'],
        attachments: [attachment],
      });

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([page]),
        getDescendantPages: vi.fn().mockResolvedValue([]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, baseProcessingConfig, enabledAttachmentConfig);
      const result = await scanner.discoverPages();

      expect(result.attachments[0]?.versionTimestamp).toBe('2026-02-01T00:00:00.000Z');
    });

    it('extracts attachments from descendant pages', async () => {
      const parent = makePage('parent', { labels: ['ai-ingest-all'] });
      const attachment = makeAttachment('att-1', 'child-doc.docx');
      const child = makePage('child', {
        labels: ['engineering'],
        attachments: [attachment],
      });

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([parent]),
        getDescendantPages: vi.fn().mockResolvedValue([child]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, baseProcessingConfig, enabledAttachmentConfig);
      const result = await scanner.discoverPages();

      expect(result.attachments).toHaveLength(1);
      expect(result.attachments[0]?.pageId).toBe('child');
    });

    it('normalizes file extension to lowercase for filtering', async () => {
      const attachment = makeAttachment('att-1', 'Report.PDF');
      const page = makePage('page-1', {
        labels: ['ai-ingest'],
        attachments: [attachment],
      });

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([page]),
        getDescendantPages: vi.fn().mockResolvedValue([]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, baseProcessingConfig, enabledAttachmentConfig);
      const result = await scanner.discoverPages();

      expect(result.attachments.map((a) => a.id)).toEqual(['att-1']);
    });

    it('counts attachments toward maxItemsToScan limit', async () => {
      const att1 = makeAttachment('att-1', 'a.pdf');
      const att2 = makeAttachment('att-2', 'b.pdf');
      const page1 = makePage('page-1', {
        labels: ['ai-ingest'],
        attachments: [att1, att2],
      });
      const page2 = makePage('page-2', { labels: ['ai-ingest'] });
      const page3 = makePage('page-3', { labels: ['ai-ingest'] });

      const limitedConfig: ProcessingConfig = {
        ...baseProcessingConfig,
        maxItemsToScan: 4,
      };

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([page1, page2, page3]),
        getDescendantPages: vi.fn().mockResolvedValue([]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, limitedConfig, enabledAttachmentConfig);
      const result = await scanner.discoverPages();

      // Pages are discovered first (3 pages, all under limit of 4),
      // then attachments fill the remaining budget (4 - 3 = 1 attachment).
      expect(result.pages.map((p) => p.id)).toEqual(['page-1', 'page-2', 'page-3']);
      expect(result.attachments.map((a) => a.id)).toEqual(['att-1']);
    });

    it('truncates attachments mid-page when limit is reached', async () => {
      const att1 = makeAttachment('att-1', 'a.pdf');
      const att2 = makeAttachment('att-2', 'b.pdf');
      const page = makePage('page-1', {
        labels: ['ai-ingest'],
        attachments: [att1, att2],
      });

      const limitedConfig: ProcessingConfig = {
        ...baseProcessingConfig,
        maxItemsToScan: 2,
      };

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([page]),
        getDescendantPages: vi.fn().mockResolvedValue([]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, limitedConfig, enabledAttachmentConfig);
      const result = await scanner.discoverPages();

      expect(result.pages).toHaveLength(1);
      expect(result.attachments).toHaveLength(1);
      expect(result.attachments[0]?.id).toBe('att-1');
    });

    it('logs attachment count when attachments are discovered', async () => {
      const att1 = makeAttachment('att-1', 'a.pdf');
      const att2 = makeAttachment('att-2', 'b.docx');
      const page = makePage('page-1', {
        labels: ['ai-ingest'],
        attachments: [att1, att2],
      });

      const apiClient = {
        searchPagesByLabel: vi.fn().mockResolvedValue([page]),
        getDescendantPages: vi.fn().mockResolvedValue([]),
        buildPageWebUrl: vi.fn(
          (p: ConfluencePage) => `https://confluence.example.com/wiki/${p.id}`,
        ),
      };

      const scanner = createScanner(apiClient, baseProcessingConfig, enabledAttachmentConfig);
      await scanner.discoverPages();

      expect(mockLogger.log).toHaveBeenCalledWith({
        count: 2,
        msg: 'Attachment discovery completed',
      });
    });
  });
});
