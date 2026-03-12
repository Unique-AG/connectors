import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import {
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
import type { FileDiffResult } from '../sync.types';

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
} as unknown as ScopeManagementService;

function createService(
  scanner: Pick<ConfluencePageScanner, 'discoverPages'>,
  contentFetcher: Pick<ConfluenceContentFetcher, 'fetchPageContent'>,
  fileDiffService: Pick<FileDiffService, 'computeDiff'>,
  ingestionService: Pick<IngestionService, 'ingestPage' | 'deleteContentByKeys'>,
): ConfluenceSynchronizationService {
  return new ConfluenceSynchronizationService(
    scanner as ConfluencePageScanner,
    contentFetcher as ConfluenceContentFetcher,
    fileDiffService as FileDiffService,
    ingestionService as IngestionService,
    mockScopeManagementService,
  );
}

describe('ConfluenceSynchronizationService', () => {
  let tenant: TenantContext;
  let mockScanner: Pick<ConfluencePageScanner, 'discoverPages'>;
  let mockContentFetcher: Pick<ConfluenceContentFetcher, 'fetchPageContent'>;
  let mockFileDiffService: Pick<FileDiffService, 'computeDiff'>;
  let mockIngestionService: Pick<IngestionService, 'ingestPage' | 'deleteContentByKeys'>;
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
      deletedItemIds: [],
      movedItemIds: [],
    };
    mockFileDiffService = {
      computeDiff: vi.fn().mockResolvedValue(diffResult),
    };
    mockIngestionService = {
      ingestPage: vi.fn().mockResolvedValue(undefined),
      deleteContentByKeys: vi.fn().mockResolvedValue(undefined),
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
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ err: expect.any(Error), msg: 'Page ingestion failed' }),
      );
    });

    it('deletes content for deleted keys returned by file diff', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['1'],
        updatedItemIds: [],
        deletedItemIds: ['99', '99_attachment.pdf'],
        movedItemIds: [],
      });

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockIngestionService.deleteContentByKeys).toHaveBeenCalledWith([
        '99',
        '99_attachment.pdf',
      ]);
    });

    it('handles no-change diffs without deleting content', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: [],
        updatedItemIds: [],
        deletedItemIds: [],
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
        { ...baseDiscovered, id: '2', title: 'Page 2' },
        { ...baseDiscovered, id: '3', title: 'Page 3' },
      ];
      vi.mocked(mockScanner.discoverPages).mockResolvedValue({
        pages: discovered,
        attachments: [],
      });
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newItemIds: ['2'],
        updatedItemIds: ['3'],
        deletedItemIds: [],
        movedItemIds: [],
      });
      // biome-ignore lint/style/noNonNullAssertion: fixture has at least one entry by construction
      const baseFetched = fetchedPagesFixture[0]!;
      vi.mocked(mockContentFetcher.fetchPageContent).mockImplementation((page: { id: string }) => {
        if (page.id === '2') {
          return Promise.resolve({ ...baseFetched, id: '2', title: 'Page 2' });
        }
        if (page.id === '3') {
          return Promise.resolve({ ...baseFetched, id: '3', title: 'Page 3' });
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
  });
});
