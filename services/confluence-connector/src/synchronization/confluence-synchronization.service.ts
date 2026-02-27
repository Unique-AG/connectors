import pLimit from 'p-limit';
import type pino from 'pino';
import { getCurrentTenant } from '../tenant';
import type { ConfluenceContentFetcher } from './confluence-content-fetcher';
import type { ConfluencePageScanner } from './confluence-page-scanner';
import type { FileDiffService } from './file-diff.service';
import type { IngestionService } from './ingestion.service';
import type { ScopeManagementService } from './scope-management.service';
import type { FetchedPage } from './sync.types';

export class ConfluenceSynchronizationService {
  public constructor(
    private readonly scanner: ConfluencePageScanner,
    private readonly contentFetcher: ConfluenceContentFetcher,
    private readonly fileDiffService: FileDiffService,
    private readonly ingestionService: IngestionService,
    private readonly scopeManagementService: ScopeManagementService,
    private readonly logger: pino.Logger,
  ) {}

  public async synchronize(): Promise<void> {
    const tenant = getCurrentTenant();

    if (tenant.isScanning) {
      this.logger.info('Sync already in progress, skipping');
      return;
    }

    tenant.isScanning = true;
    try {
      this.logger.info('Starting sync');

      await this.scopeManagementService.initialize();

      const discoveredPages = await this.scanner.discoverPages();
      this.logger.info({ count: discoveredPages.length }, 'Discovery completed');

      const diff = await this.fileDiffService.computeDiff(discoveredPages);
      this.logger.info(
        {
          new: diff.newPageIds.length,
          updated: diff.updatedPageIds.length,
          deleted: diff.deletedPageIds.length,
          moved: diff.movedPageIds.length,
        },
        'File diff completed',
      );

      const pageIdsToFetch = new Set([...diff.newPageIds, ...diff.updatedPageIds]);
      const pagesToFetch = discoveredPages.filter((p) => pageIdsToFetch.has(p.id));

      const fetchedPages = await this.contentFetcher.fetchPagesContent(pagesToFetch);
      this.logger.info({ count: fetchedPages.length }, 'Content fetching completed');

      const concurrency = Math.max(1, tenant.config.processing.concurrency);

      await this.ingestPagesWithConcurrency(fetchedPages, concurrency);

      if (diff.deletedKeys.length > 0) {
        await this.ingestionService.deleteContent(diff.deletedKeys);
        this.logger.info({ count: diff.deletedKeys.length }, 'Deleted content processed');
      }

      this.logger.info('Sync completed');
    } catch (error) {
      this.logger.error({ err: error, msg: 'Sync failed' });
    } finally {
      tenant.isScanning = false;
    }
  }

  private async ingestPagesWithConcurrency(
    pages: FetchedPage[],
    concurrency: number,
  ): Promise<void> {
    const limit = pLimit(concurrency);

    await Promise.all(
      pages.map((page) => limit(() => this.ingestionService.ingestPage(page))),
    );

    this.logger.info({ count: pages.length }, 'Page ingestion completed');
  }
}
