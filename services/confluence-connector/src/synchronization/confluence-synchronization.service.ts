import assert from 'assert';
import { Logger } from '@nestjs/common';
import pLimit from 'p-limit';
import { getCurrentTenant } from '../tenant';
import type { ConfluenceContentFetcher } from './confluence-content-fetcher';
import type { ConfluencePageScanner } from './confluence-page-scanner';
import type { FileDiffService } from './file-diff.service';
import type { IngestionService } from './ingestion.service';
import type { ScopeManagementService } from './scope-management.service';
import type { DiscoveredPage } from './sync.types';

export class ConfluenceSynchronizationService {
  private readonly logger = new Logger(ConfluenceSynchronizationService.name);

  public constructor(
    private readonly scanner: ConfluencePageScanner,
    private readonly contentFetcher: ConfluenceContentFetcher,
    private readonly fileDiffService: FileDiffService,
    private readonly ingestionService: IngestionService,
    private readonly scopeManagementService: ScopeManagementService,
  ) {}

  public async synchronize(): Promise<void> {
    const tenant = getCurrentTenant();

    if (tenant.isScanning) {
      this.logger.log({ tenantName: tenant.name, msg: 'Sync already in progress, skipping' });
      return;
    }

    tenant.isScanning = true;
    try {
      this.logger.log({ tenantName: tenant.name, msg: 'Starting sync' });

      await this.scopeManagementService.initialize();

      const discoveredPages = await this.scanner.discoverPages();
      this.logger.log({ count: discoveredPages.length, msg: 'Discovery completed' });

      const diffResult = await this.fileDiffService.computeDiff(discoveredPages);
      this.logger.log({
        new: diffResult.newPageIds.length,
        updated: diffResult.updatedPageIds.length,
        deleted: diffResult.deletedPageIds.length,
        moved: diffResult.movedPageIds.length,
        msg: 'File diff completed',
      });

      const pageIdsToFetch = new Set([...diffResult.newPageIds, ...diffResult.updatedPageIds]);
      const pagesToFetch = discoveredPages.filter((p) => pageIdsToFetch.has(p.id));

      const spaceKeys = pagesToFetch.map((p) => p.spaceKey);
      const spaceScopes = await this.scopeManagementService.ensureSpaceScopes(spaceKeys);

      await this.fetchAndIngestPages(pagesToFetch, spaceScopes, tenant.config.processing.concurrency);

      if (diffResult.deletedKeys.length > 0) {
        await this.ingestionService.deleteContent(diffResult.deletedKeys);
        this.logger.log({ count: diffResult.deletedKeys.length, msg: 'Deleted content processed' });
      }

      this.logger.log('Sync completed');
    } catch (error) {
      this.logger.error({ err: error, msg: 'Sync failed' });
    } finally {
      tenant.isScanning = false;
    }
  }

  private async fetchAndIngestPages(
    pages: DiscoveredPage[],
    spaceScopes: Map<string, string>,
    concurrency: number,
  ): Promise<void> {
    const limit = pLimit(concurrency);

    await Promise.all(
      pages.map((page) => limit(async () => {
        const fetched = await this.contentFetcher.fetchPageContent(page);

        if (!fetched) {
          return;
        }
        const scopeId = spaceScopes.get(page.spaceKey);
        assert.ok(scopeId, `No scope resolved for space: ${page.spaceKey}`);
        await this.ingestionService.ingestPage(fetched, scopeId);
      }),
    ))

    this.logger.log({ count: pages.length, msg: 'Page ingestion completed' });
  }
}
