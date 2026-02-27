import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import type { ConfluenceContentFetcher } from '../confluence-content-fetcher';
import type { ConfluencePageScanner } from '../confluence-page-scanner';
import { ConfluenceSynchronizationService } from '../confluence-synchronization.service';
import type { FileDiffService } from '../file-diff.service';
import type { IngestionService } from '../ingestion.service';
import type { ScopeManagementService } from '../scope-management.service';
import type { FileDiffResult } from '../sync.types';
import {
  CONFLUENCE_BASE_URL,
  createMockTenant,
  discoveredPagesFixture,
  fetchedPagesFixture,
} from '../__mocks__/sync.fixtures';

const mockTenantLogger = vi.hoisted(() => ({
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

const mockScopeManagementService = {
  initialize: vi.fn().mockResolvedValue(undefined),
} as unknown as ScopeManagementService;

function createService(
  scanner: Pick<ConfluencePageScanner, 'discoverPages'>,
  contentFetcher: Pick<ConfluenceContentFetcher, 'fetchPagesContent'>,
  fileDiffService: Pick<FileDiffService, 'computeDiff'>,
  ingestionService: Pick<IngestionService, 'ingestPage' | 'ingestFiles' | 'deleteContent'>,
): ConfluenceSynchronizationService {
  return new ConfluenceSynchronizationService(
    scanner as ConfluencePageScanner,
    contentFetcher as ConfluenceContentFetcher,
    fileDiffService as FileDiffService,
    ingestionService as IngestionService,
    mockScopeManagementService,
    mockTenantLogger as never,
  );
}

describe('ConfluenceSynchronizationService', () => {
  let tenant: TenantContext;
  let mockScanner: Pick<ConfluencePageScanner, 'discoverPages'>;
  let mockContentFetcher: Pick<ConfluenceContentFetcher, 'fetchPagesContent'>;
  let mockFileDiffService: Pick<FileDiffService, 'computeDiff'>;
  let mockIngestionService: Pick<IngestionService, 'ingestPage' | 'ingestFiles' | 'deleteContent'>;
  let service: ConfluenceSynchronizationService;

  beforeEach(() => {
    vi.clearAllMocks();
    tenant = createMockTenant('test-tenant');
    mockScanner = {
      discoverPages: vi.fn().mockResolvedValue(discoveredPagesFixture),
    };
    mockContentFetcher = {
      fetchPagesContent: vi.fn().mockResolvedValue(fetchedPagesFixture),
    };
    const diffResult: FileDiffResult = {
      newPageIds: ['1'],
      updatedPageIds: [],
      deletedPageIds: [],
      movedPageIds: [],
      deletedKeys: [],
    };
    mockFileDiffService = {
      computeDiff: vi.fn().mockResolvedValue(diffResult),
    };
    mockIngestionService = {
      ingestPage: vi.fn().mockResolvedValue(undefined),
      ingestFiles: vi.fn().mockResolvedValue(undefined),
      deleteContent: vi.fn().mockResolvedValue(undefined),
    };
    service = createService(mockScanner, mockContentFetcher, mockFileDiffService, mockIngestionService);
  });

  describe('synchronize', () => {
    it('skips when tenant is already scanning', async () => {
      tenant.isScanning = true;

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Sync already in progress, skipping');
      expect(mockScanner.discoverPages).not.toHaveBeenCalled();
      expect(mockContentFetcher.fetchPagesContent).not.toHaveBeenCalled();
    });

    it('runs scanner then content fetcher and logs summaries', async () => {
      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Starting sync');
      expect(mockScanner.discoverPages).toHaveBeenCalledOnce();
      expect(mockFileDiffService.computeDiff).toHaveBeenCalledWith(discoveredPagesFixture);
      expect(mockContentFetcher.fetchPagesContent).toHaveBeenCalledWith(discoveredPagesFixture);
      expect(mockIngestionService.ingestPage).toHaveBeenCalledWith(fetchedPagesFixture[0]);

      const discoverLog = mockTenantLogger.info.mock.calls.find(
        (call) => typeof call[1] === 'string' && call[1].startsWith('Discovery completed'),
      );
      expect(discoverLog).toBeDefined();
      expect(discoverLog?.[0]).toMatchObject({ count: discoveredPagesFixture.length });

      const fetchLog = mockTenantLogger.info.mock.calls.find(
        (call) => typeof call[1] === 'string' && call[1].startsWith('Content fetching completed'),
      );
      expect(fetchLog).toBeDefined();
      expect(fetchLog?.[0]).toMatchObject({ count: fetchedPagesFixture.length });

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Sync completed');
    });

    it('resets isScanning after successful sync', async () => {
      await tenantStorage.run(tenant, () => service.synchronize());
      expect(tenant.isScanning).toBe(false);
    });

    it('resets isScanning and logs errors when scanner fails', async () => {
      vi.mocked(mockScanner.discoverPages).mockRejectedValue(new Error('discovery failure'));

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
      expect(mockTenantLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ err: expect.any(Error), msg: 'Sync failed' }),
      );
    });

    it('resets isScanning and logs errors when content fetcher fails', async () => {
      vi.mocked(mockContentFetcher.fetchPagesContent).mockRejectedValue(new Error('fetch failure'));

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
      expect(mockTenantLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ err: expect.any(Error), msg: 'Sync failed' }),
      );
    });

    it('deletes content for deleted keys returned by file diff', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newPageIds: ['1'],
        updatedPageIds: [],
        deletedPageIds: ['99'],
        movedPageIds: [],
        deletedKeys: ['99', '99_attachment.pdf'],
      });

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockIngestionService.deleteContent).toHaveBeenCalledWith(['99', '99_attachment.pdf']);
    });

    it('ingests linked files when file ingestion is enabled', async () => {
      tenant = createMockTenant('test-tenant', {
        config: {
          ...tenant.config,
          ingestion: {
            ingestFiles: 'enabled',
            allowedFileExtensions: ['pdf'],
          },
        } as TenantContext['config'],
      });
      service = createService(
        mockScanner,
        {
          fetchPagesContent: vi.fn().mockResolvedValue([
            {
              ...fetchedPagesFixture[0],
              body: '<a href="/files/guide.pdf?download=true">PDF</a>',
            },
          ]),
        },
        mockFileDiffService,
        mockIngestionService,
      );

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockIngestionService.ingestFiles).toHaveBeenCalledWith(
        expect.objectContaining({ id: '1' }),
        [`${CONFLUENCE_BASE_URL}/files/guide.pdf?download=true`],
      );
    });

    it('handles no-change diffs without deleting content', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newPageIds: [],
        updatedPageIds: [],
        deletedPageIds: [],
        movedPageIds: [],
        deletedKeys: [],
      });
      vi.mocked(mockContentFetcher.fetchPagesContent).mockResolvedValue([]);

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockContentFetcher.fetchPagesContent).toHaveBeenCalledWith([]);
      expect(mockIngestionService.ingestPage).not.toHaveBeenCalled();
      expect(mockIngestionService.deleteContent).not.toHaveBeenCalled();
    });

    it('logs and exits when file diff fails', async () => {
      vi.mocked(mockFileDiffService.computeDiff).mockRejectedValue(new Error('diff failed'));

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
      expect(mockTenantLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ err: expect.any(Error), msg: 'Sync failed' }),
      );
      expect(mockContentFetcher.fetchPagesContent).not.toHaveBeenCalled();
    });

    it('fetches content only for new and updated pages from diff', async () => {
      // biome-ignore lint/style/noNonNullAssertion: fixture has at least one entry by construction
      const baseDiscovered = discoveredPagesFixture[0]!;
      const discovered = [
        ...discoveredPagesFixture,
        { ...baseDiscovered, id: '2', title: 'Page 2' },
        { ...baseDiscovered, id: '3', title: 'Page 3' },
      ];
      vi.mocked(mockScanner.discoverPages).mockResolvedValue(discovered);
      vi.mocked(mockFileDiffService.computeDiff).mockResolvedValue({
        newPageIds: ['2'],
        updatedPageIds: ['3'],
        deletedPageIds: [],
        movedPageIds: [],
        deletedKeys: [],
      });
      // biome-ignore lint/style/noNonNullAssertion: fixture has at least one entry by construction
      const baseFetched = fetchedPagesFixture[0]!;
      const fetchedSubset = [
        { ...baseFetched, id: '2', title: 'Page 2' },
        { ...baseFetched, id: '3', title: 'Page 3' },
      ];
      vi.mocked(mockContentFetcher.fetchPagesContent).mockResolvedValue(fetchedSubset);

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockContentFetcher.fetchPagesContent).toHaveBeenCalledWith([
        expect.objectContaining({ id: '2' }),
        expect.objectContaining({ id: '3' }),
      ]);
      expect(mockIngestionService.ingestPage).toHaveBeenCalledWith(
        expect.objectContaining({ id: '2' }),
      );
      expect(mockIngestionService.ingestPage).toHaveBeenCalledWith(
        expect.objectContaining({ id: '3' }),
      );
      expect(mockIngestionService.ingestPage).not.toHaveBeenCalledWith(
        expect.objectContaining({ id: '1' }),
      );
    });
  });
});
