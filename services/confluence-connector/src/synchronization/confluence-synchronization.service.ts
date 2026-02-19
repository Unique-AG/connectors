import pLimit from 'p-limit';
import type pino from 'pino';
import { IngestFiles } from '../constants/ingestion.constants';
import type { ServiceRegistry } from '../tenant';
import { getCurrentTenant } from '../tenant/tenant-context.storage';
import { extractFileUrls } from '../utils/html-link-parser';
import { sanitizeError } from '../utils/normalize-error';
import { ConfluenceContentFetcher } from './confluence-content-fetcher';
import { ConfluencePageScanner } from './confluence-page-scanner';
import { FileDiffService } from './file-diff.service';
import { IngestionService } from './ingestion.service';
import type { FetchedPage } from './sync.types';

export class ConfluenceSynchronizationService {
  private readonly scanner: ConfluencePageScanner;
  private readonly contentFetcher: ConfluenceContentFetcher;
  private readonly fileDiffService: FileDiffService;
  private readonly ingestionService: IngestionService;
  private readonly logger: pino.Logger;

  public constructor(serviceRegistry: ServiceRegistry) {
    this.scanner = serviceRegistry.getService(ConfluencePageScanner);
    this.contentFetcher = serviceRegistry.getService(ConfluenceContentFetcher);
    this.fileDiffService = serviceRegistry.getService(FileDiffService);
    this.ingestionService = serviceRegistry.getService(IngestionService);
    this.logger = serviceRegistry.getServiceLogger(ConfluenceSynchronizationService);
  }

  public async synchronize(): Promise<void> {
    const tenant = getCurrentTenant();

    if (tenant.isScanning) {
      this.logger.info('Sync already in progress, skipping');
      return;
    }

    tenant.isScanning = true;
    try {
      this.logger.info('Starting sync');

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
      const fileIngestionEnabled = tenant.config.ingestion.ingestFiles === IngestFiles.Enabled;
      const allowedExtensions = tenant.config.ingestion.allowedFileExtensions ?? [];
      const confluenceBaseUrl = tenant.config.confluence.baseUrl;

      await this.ingestPagesWithConcurrency(
        fetchedPages,
        concurrency,
        fileIngestionEnabled,
        allowedExtensions,
        confluenceBaseUrl,
      );

      if (diff.deletedKeys.length > 0) {
        await this.ingestionService.deleteContent(diff.deletedKeys);
        this.logger.info({ count: diff.deletedKeys.length }, 'Deleted content processed');
      }

      this.logger.info('Sync completed');
    } catch (error) {
      this.logger.error({ msg: 'Sync failed', error: sanitizeError(error) });
    } finally {
      tenant.isScanning = false;
    }
  }

  private async ingestPagesWithConcurrency(
    pages: FetchedPage[],
    concurrency: number,
    fileIngestionEnabled: boolean,
    allowedExtensions: string[],
    confluenceBaseUrl: string,
  ): Promise<void> {
    const limit = pLimit(concurrency);

    await Promise.all(
      pages.map((page) =>
        limit(() =>
          this.ingestPageAndFiles(page, fileIngestionEnabled, allowedExtensions, confluenceBaseUrl),
        ),
      ),
    );

    this.logger.info({ count: pages.length }, 'Page ingestion completed');
  }

  private async ingestPageAndFiles(
    page: FetchedPage,
    fileIngestionEnabled: boolean,
    allowedExtensions: string[],
    confluenceBaseUrl: string,
  ): Promise<void> {
    await this.ingestionService.ingestPage(page);

    if (fileIngestionEnabled && page.body) {
      const fileUrls = extractFileUrls(page.body, allowedExtensions, confluenceBaseUrl);
      if (fileUrls.length > 0) {
        await this.ingestionService.ingestFiles(page, fileUrls);
      }
    }
  }
}
