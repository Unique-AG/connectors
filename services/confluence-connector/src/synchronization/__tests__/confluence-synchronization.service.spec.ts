import { Smeared } from '@unique-ag/utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type Metrics, SyncPhase } from '../../metrics';
import { createNoopMetrics } from '../../metrics/__mocks__/noop-metrics';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import {
  CONFLUENCE_BASE_URL,
  createMockTenant,
  discoveredPagesFixture,
  discoveryResultFixture,
  fetchedPagesFixture,
} from '../__mocks__/sync.fixtures';
import type { ConfluenceContentFetcher } from '../confluence-content-fetcher';
import type { ConfluencePageScanner } from '../confluence-page-scanner';
import { ConfluenceSynchronizationService } from '../confluence-synchronization.service';
import type { FileDiffService } from '../file-diff.service';
import type { IngestionService } from '../ingestion.service';
import type { ScopeManagementService } from '../scope-management.service';
import type { DiscoveredAttachment, FileDiffResult } from '../sync.types';

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

const mockScopeManagementService = {
  initialize: vi.fn().mockResolvedValue('/Confluence'),
  ensureSpaceScopes: vi.fn().mockResolvedValue(new Map([['SP', 'scope-1']])),
  cleanupRemovedSpaces: vi.fn().mockResolvedValue(undefined),
} as unknown as ScopeManagementService;

function createService(
  scanner: Pick<ConfluencePageScanner, 'discoverPages'>,
  contentFetcher: Pick<ConfluenceContentFetcher, 'fetchPageContent'>,
  fileDiffService: Pick<FileDiffService, 'computeDiff'>,
  ingestionService: Pick<
    IngestionService,
    'ingestPage' | 'ingestAttachment' | 'deleteContentByKeys'
  >,
  metrics: Metrics = createNoopMetrics(),
): ConfluenceSynchronizationService {
  return new ConfluenceSynchronizationService(
    scanner as ConfluencePageScanner,
    contentFetcher as ConfluenceContentFetcher,
    fileDiffService as FileDiffService,
    ingestionService as IngestionService,
    mockScopeManagementService,
    metrics,
  );
}

function createMetricsSpy(): Metrics {
  const base = createNoopMetrics();
  const spy = { ...base } as Record<string, unknown>;
  for (const key of Object.keys(spy)) {
    spy[key] = vi.fn();
  }
  return spy as unknown as Metrics;
}

describe('ConfluenceSynchronizationService', () => {
  let tenant: TenantContext;
  let mockScanner: Pick<ConfluencePageScanner, 'discoverPages'>;
  let mockContentFetcher: Pick<ConfluenceContentFetcher, 'fetchPageContent'>;
  let mockFileDiffService: Pick<FileDiffService, 'computeDiff'>;
  let mockIngestionService: Pick<
    IngestionService,
    'ingestPage' | 'ingestAttachment' | 'deleteContentByKeys'
  >;
  let service: ConfluenceSynchronizationService;

  beforeEach(() => {
    vi.clearAllMocks();
    tenant = createMockTenant('test-tenant');
    mockScanner = {
      discoverPages: vi.fn().mockResolvedValue(discoveryResultFixture),
    };
    mockContentFetcher = {
      fetchPageContent: vi.fn().mockImplementation((page: { id: string }) => {
        const fetched = fetchedPagesFixture.find((f) => f.id === page.id);
        return Promise.resolve(fetched ?? null);
      }),
    };
    const diffResult: FileDiffResult = {
      newItemIds: ['1'],
      updatedItemIds: [],
      deletedItems: [],
      movedItemIds: [],
    };
    mockFileDiffService = {
      computeDiff: vi.fn().mockResolvedValue(diffResult),
    };
    mockIngestionService = {
      ingestPage: vi.fn().mockResolvedValue(undefined),
      ingestAttachment: vi.fn().mockResolvedValue(undefined),
      deleteContentByKeys: vi.fn().mockResolvedValue(0),
    };
    service = createService(
      mockScanner,
      mockContentFetcher,
      mockFileDiffService,
      mockIngestionService,
    );
  });

  describe('synchronize', () => {
    it('skips when tenant is already scanning', async () => {
      tenant.isScanning = true;

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Sync already in progress, skipping' }),
      );
      expect(mockScanner.discoverPages).not.toHaveBeenCalled();
      expect(mockContentFetcher.fetchPageContent).not.toHaveBeenCalled();
    });

    it('runs scanner then content fetcher and logs summaries', async () => {
      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Starting sync' }),
      );
      expect(mockScanner.discoverPages).toHaveBeenCalledOnce();
      expect(mockFileDiffService.computeDiff).toHaveBeenCalledWith(
        discoveredPagesFixture,
        discoveryResultFixture.attachments,
      );
      expect(mockContentFetcher.fetchPageContent).toHaveBeenCalledWith(
        expect.objectContaining({ id: '1' }),
      );
      expect(mockIngestionService.ingestPage).toHaveBeenCalledWith(
        fetchedPagesFixture[0],
        'scope-1',
      );

      expect(mockLogger.log).toHaveBeenCalledWith(
        expect.objectContaining({
          count: discoveredPagesFixture.length,
          msg: 'Discovery completed',
        }),
      );

      expect(mockLogger.log).toHaveBeenCalledWith({ msg: 'Sync work done' });
    });

    it('resets isScanning after successful sync', async () => {
      await tenantStorage.run(tenant, () => service.synchronize());
      expect(tenant.isScanning).toBe(false);
    });

    it('resets isScanning and logs errors when scanner fails', async () => {
      vi.mocked(mockScanner.discoverPages).mockRejectedValue(new Error('discovery failure'));

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ err: expect.any(Error), msg: 'Sync failed' }),
      );
    });

    it('logs individual page failures without aborting the sync', async () => {
      vi.mocked(mockContentFetcher.fetchPageContent).mockRejectedValue(new Error('fetch failure'));

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
      expect(mockLogger.log).toHaveBeenCalledWith({
        total: 1,
        ingested: 0,
        skipped: 0,
        failed: 1,
        msg: 'Page ingestion summary',
      });
    });

    it('deletes content for deleted keys returned by file diff', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['1'],
        updatedItemIds: [],
        deletedItems: [
          { id: '99', partialKey: 'test-tenant/space-1_SP' },
          { id: '99_attachment.pdf', partialKey: 'test-tenant/space-1_SP' },
        ],
        movedItemIds: [],
      });

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockIngestionService.deleteContentByKeys).toHaveBeenCalledWith([
        'test-tenant/space-1_SP/99',
        'test-tenant/space-1_SP/99_attachment.pdf',
      ]);
    });

    it('handles no-change diffs without deleting content', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: [],
        updatedItemIds: [],
        deletedItems: [],
        movedItemIds: [],
      });
      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockContentFetcher.fetchPageContent).not.toHaveBeenCalled();
      expect(mockIngestionService.ingestPage).not.toHaveBeenCalled();
      expect(mockIngestionService.deleteContentByKeys).not.toHaveBeenCalled();
    });

    it('logs and exits when file diff fails', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockRejectedValue(new Error('diff failed'));

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ err: expect.any(Error), msg: 'Sync failed' }),
      );
      expect(mockContentFetcher.fetchPageContent).not.toHaveBeenCalled();
    });

    it('fetches content only for new and updated pages from diff', async () => {
      // biome-ignore lint/style/noNonNullAssertion: fixture has at least one entry by construction
      const baseDiscovered = discoveredPagesFixture[0]!;
      const discovered = [
        ...discoveredPagesFixture,
        { ...baseDiscovered, id: '2', title: new Smeared('Page 2', false) },
        { ...baseDiscovered, id: '3', title: new Smeared('Page 3', false) },
      ];
      vi.mocked(mockScanner.discoverPages).mockResolvedValue({
        pages: discovered,
        attachments: [],
      });
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['2'],
        updatedItemIds: ['3'],
        deletedItems: [],
        movedItemIds: [],
      });
      // biome-ignore lint/style/noNonNullAssertion: fixture has at least one entry by construction
      const baseFetched = fetchedPagesFixture[0]!;
      vi.mocked(mockContentFetcher.fetchPageContent).mockImplementation((page: { id: string }) => {
        if (page.id === '2') {
          return Promise.resolve({ ...baseFetched, id: '2', title: new Smeared('Page 2', false) });
        }
        if (page.id === '3') {
          return Promise.resolve({ ...baseFetched, id: '3', title: new Smeared('Page 3', false) });
        }
        return Promise.resolve(null);
      });

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockContentFetcher.fetchPageContent).toHaveBeenCalledWith(
        expect.objectContaining({ id: '2' }),
      );
      expect(mockContentFetcher.fetchPageContent).toHaveBeenCalledWith(
        expect.objectContaining({ id: '3' }),
      );
      expect(mockIngestionService.ingestPage).toHaveBeenCalledWith(
        expect.objectContaining({ id: '2' }),
        'scope-1',
      );
      expect(mockIngestionService.ingestPage).toHaveBeenCalledWith(
        expect.objectContaining({ id: '3' }),
        'scope-1',
      );
      expect(mockIngestionService.ingestPage).not.toHaveBeenCalledWith(
        expect.objectContaining({ id: '1' }),
        expect.anything(),
      );
    });

    it('ingests new and updated attachments from diff', async () => {
      const attachment: DiscoveredAttachment = {
        id: 'att-1',
        title: 'report.pdf',
        mediaType: 'application/pdf',
        fileSize: 1024,
        downloadPath: '/download/attachments/1/report.pdf',
        versionTimestamp: '2026-02-01T00:00:00.000Z',
        pageId: '1',
        spaceId: 'space-1',
        spaceKey: 'SP',
        spaceName: 'Space',
        webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP/pages/1/attachments/att-1`,
      };
      vi.mocked(mockScanner.discoverPages).mockResolvedValue({
        pages: discoveredPagesFixture,
        attachments: [attachment],
      });
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['1', '1::att-1'],
        updatedItemIds: [],
        deletedItems: [],
        movedItemIds: [],
      });

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockIngestionService.ingestAttachment).toHaveBeenCalledWith(attachment, 'scope-1');
      expect(mockIngestionService.ingestPage).toHaveBeenCalledWith(
        fetchedPagesFixture[0],
        'scope-1',
      );
    });

    it('does not ingest attachments not in diff result', async () => {
      const attachment: DiscoveredAttachment = {
        id: 'att-1',
        title: 'report.pdf',
        mediaType: 'application/pdf',
        fileSize: 1024,
        downloadPath: '/download/attachments/1/report.pdf',
        versionTimestamp: '2026-02-01T00:00:00.000Z',
        pageId: '1',
        spaceId: 'space-1',
        spaceKey: 'SP',
        spaceName: 'Space',
        webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP/pages/1/attachments/att-1`,
      };
      vi.mocked(mockScanner.discoverPages).mockResolvedValue({
        pages: discoveredPagesFixture,
        attachments: [attachment],
      });
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['1'],
        updatedItemIds: [],
        deletedItems: [],
        movedItemIds: [],
      });

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockIngestionService.ingestAttachment).not.toHaveBeenCalled();
    });

    it('ensures space scopes include attachment spaces', async () => {
      const attachment: DiscoveredAttachment = {
        id: 'att-1',
        title: 'report.pdf',
        mediaType: 'application/pdf',
        fileSize: 1024,
        downloadPath: '/download/attachments/1/report.pdf',
        versionTimestamp: '2026-02-01T00:00:00.000Z',
        pageId: '1',
        spaceId: 'space-2',
        spaceKey: 'SP2',
        spaceName: 'Space 2',
        webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP2/pages/1/attachments/att-1`,
      };
      vi.mocked(mockScanner.discoverPages).mockResolvedValue({
        pages: [],
        attachments: [attachment],
      });
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['1::att-1'],
        updatedItemIds: [],
        deletedItems: [],
        movedItemIds: [],
      });
      vi.mocked(mockScopeManagementService.ensureSpaceScopes).mockResolvedValue(
        new Map([['SP2', 'scope-2']]),
      );

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockScopeManagementService.ensureSpaceScopes).toHaveBeenCalledWith(
        '/Confluence',
        ['SP2'],
        new Map([['SP2', 'space-2']]),
      );
      expect(mockIngestionService.ingestAttachment).toHaveBeenCalledWith(attachment, 'scope-2');
    });

    it('calls cleanupRemovedSpaces with discovered spaceKeys from pages and attachments', async () => {
      const attachment: DiscoveredAttachment = {
        id: 'att-1',
        title: 'report.pdf',
        mediaType: 'application/pdf',
        fileSize: 1024,
        downloadPath: '/download/attachments/1/report.pdf',
        versionTimestamp: '2026-02-01T00:00:00.000Z',
        pageId: '1',
        spaceId: 'space-2',
        spaceKey: 'SP2',
        spaceName: 'Space 2',
        webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP2/pages/1/attachments/att-1`,
      };
      vi.mocked(mockScanner.discoverPages).mockResolvedValue({
        pages: discoveredPagesFixture,
        attachments: [attachment],
      });
      vi.mocked(mockScopeManagementService.ensureSpaceScopes).mockResolvedValue(
        new Map([
          ['SP', 'scope-1'],
          ['SP2', 'scope-2'],
        ]),
      );

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockScopeManagementService.cleanupRemovedSpaces).toHaveBeenCalledWith(
        new Set(['SP', 'SP2']),
      );
    });

    it('calls cleanupRemovedSpaces with page-only spaceKeys when no attachments exist', async () => {
      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockScopeManagementService.cleanupRemovedSpaces).toHaveBeenCalledWith(new Set(['SP']));
    });

    it('skips ingestion when fetchPageContent returns null', async () => {
      vi.mocked(mockContentFetcher.fetchPageContent).mockResolvedValue(null);

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockIngestionService.ingestPage).not.toHaveBeenCalled();
    });

    it('logs individual attachment ingestion failures without aborting sync', async () => {
      const attachment: DiscoveredAttachment = {
        id: 'att-fail',
        title: 'broken.pdf',
        mediaType: 'application/pdf',
        fileSize: 1024,
        downloadPath: '/download/attachments/1/broken.pdf',
        versionTimestamp: '2026-02-01T00:00:00.000Z',
        pageId: '1',
        spaceId: 'space-1',
        spaceKey: 'SP',
        spaceName: 'Space',
        webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP/pages/1/attachments/att-fail`,
      };
      vi.mocked(mockScanner.discoverPages).mockResolvedValue({
        pages: [],
        attachments: [attachment],
      });
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['1::att-fail'],
        updatedItemIds: [],
        deletedItems: [],
        movedItemIds: [],
      });
      vi.mocked(mockIngestionService.ingestAttachment).mockRejectedValue(
        new Error('attachment ingestion boom'),
      );

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
      expect(mockLogger.log).toHaveBeenCalledWith({
        total: 1,
        ingested: 0,
        failed: 1,
        msg: 'Attachment ingestion summary',
      });
      expect(mockLogger.log).toHaveBeenCalledWith({ msg: 'Sync work done' });
    });
  });

  describe('metrics', () => {
    it('records pages per item with success, failure, and skipped results', async () => {
      // biome-ignore lint/style/noNonNullAssertion: fixture has at least one entry by construction
      const baseDiscovered = discoveredPagesFixture[0]!;
      const discovered = [
        { ...baseDiscovered, id: 'ok' },
        { ...baseDiscovered, id: 'skip' },
        { ...baseDiscovered, id: 'fail' },
      ];
      vi.mocked(mockScanner.discoverPages).mockResolvedValue({
        pages: discovered,
        attachments: [],
      });
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['ok', 'skip', 'fail'],
        updatedItemIds: [],
        deletedItems: [],
        movedItemIds: [],
      });
      // biome-ignore lint/style/noNonNullAssertion: fixture has at least one entry by construction
      const baseFetched = fetchedPagesFixture[0]!;
      vi.mocked(mockContentFetcher.fetchPageContent).mockImplementation((page: { id: string }) => {
        if (page.id === 'skip') {
          return Promise.resolve(null);
        }
        return Promise.resolve({ ...baseFetched, id: page.id });
      });
      vi.mocked(mockIngestionService.ingestPage).mockImplementation(
        ({ id }: { id: string }): Promise<void> => {
          if (id === 'fail') {
            return Promise.reject(new Error('boom'));
          }
          return Promise.resolve();
        },
      );

      const metrics = createMetricsSpy();
      const svc = createService(
        mockScanner,
        mockContentFetcher,
        mockFileDiffService,
        mockIngestionService,
        metrics,
      );

      await tenantStorage.run(tenant, () => svc.synchronize());

      expect(metrics.recordPagesProcessed).toHaveBeenCalledWith(1, 'success');
      expect(metrics.recordPagesProcessed).toHaveBeenCalledWith(1, 'skipped');
      expect(metrics.recordPagesProcessed).toHaveBeenCalledWith(1, 'failure');
      expect(vi.mocked(metrics.recordPagesProcessed).mock.calls).toHaveLength(3);
    });

    it('records attachments per item with success and failure results', async () => {
      const mkAttachment = (id: string): DiscoveredAttachment => ({
        id,
        title: `${id}.pdf`,
        mediaType: 'application/pdf',
        fileSize: 1,
        downloadPath: `/download/attachments/1/${id}.pdf`,
        versionTimestamp: '2026-02-01T00:00:00.000Z',
        pageId: '1',
        spaceId: 'space-1',
        spaceKey: 'SP',
        spaceName: 'Space',
        webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP/pages/1/attachments/${id}`,
      });
      vi.mocked(mockScanner.discoverPages).mockResolvedValue({
        pages: [],
        attachments: [mkAttachment('ok'), mkAttachment('fail')],
      });
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['1::ok', '1::fail'],
        updatedItemIds: [],
        deletedItems: [],
        movedItemIds: [],
      });
      vi.mocked(mockIngestionService.ingestAttachment).mockImplementation(
        (attachment: { id: string }): Promise<void> => {
          if (attachment.id === 'fail') {
            return Promise.reject(new Error('boom'));
          }
          return Promise.resolve();
        },
      );

      const metrics = createMetricsSpy();
      const svc = createService(
        mockScanner,
        mockContentFetcher,
        mockFileDiffService,
        mockIngestionService,
        metrics,
      );

      await tenantStorage.run(tenant, () => svc.synchronize());

      expect(metrics.recordAttachmentsProcessed).toHaveBeenCalledWith(1, 'success');
      expect(metrics.recordAttachmentsProcessed).toHaveBeenCalledWith(1, 'failure');
      expect(vi.mocked(metrics.recordAttachmentsProcessed).mock.calls).toHaveLength(2);
    });

    it('walks through sync phases and ends on Idle', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['1'],
        updatedItemIds: [],
        deletedItems: [{ id: '9', partialKey: 'test-tenant/space-1_SP' }],
        movedItemIds: [],
      });

      const metrics = createMetricsSpy();
      const svc = createService(
        mockScanner,
        mockContentFetcher,
        mockFileDiffService,
        mockIngestionService,
        metrics,
      );

      await tenantStorage.run(tenant, () => svc.synchronize());

      const phaseCalls = vi
        .mocked(metrics.setSyncPhase)
        .mock.calls.map((args: unknown[]) => args[0]);
      expect(phaseCalls).toEqual([
        SyncPhase.Scanning,
        SyncPhase.Diffing,
        SyncPhase.IngestingPages,
        SyncPhase.IngestingAttachments,
        SyncPhase.Deleting,
        SyncPhase.CleaningUp,
        SyncPhase.Idle,
      ]);
    });

    it('ends on Idle even when sync fails mid-way', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockRejectedValue(new Error('diff boom'));

      const metrics = createMetricsSpy();
      const svc = createService(
        mockScanner,
        mockContentFetcher,
        mockFileDiffService,
        mockIngestionService,
        metrics,
      );

      await tenantStorage.run(tenant, () => svc.synchronize());

      const phaseCalls = vi
        .mocked(metrics.setSyncPhase)
        .mock.calls.map((args: unknown[]) => args[0]);
      expect(phaseCalls.at(-1)).toBe(SyncPhase.Idle);
    });

    it('records sync item totals when there is work to do', async () => {
      const metrics = createMetricsSpy();
      const svc = createService(
        mockScanner,
        mockContentFetcher,
        mockFileDiffService,
        mockIngestionService,
        metrics,
      );

      await tenantStorage.run(tenant, () => svc.synchronize());

      expect(metrics.recordSyncItemTotals).toHaveBeenCalledWith(1, 0);
    });

    it('does not reset sync item totals on a no-change sync', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: [],
        updatedItemIds: [],
        deletedItems: [],
        movedItemIds: [],
      });

      const metrics = createMetricsSpy();
      const svc = createService(
        mockScanner,
        mockContentFetcher,
        mockFileDiffService,
        mockIngestionService,
        metrics,
      );

      await tenantStorage.run(tenant, () => svc.synchronize());

      expect(metrics.recordSyncItemTotals).not.toHaveBeenCalled();
    });
  });
});
