import assert from 'node:assert';
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

      const rootScopePath = await this.scopeManagementService.initialize();

      const discoveredPages = await this.scanner.discoverPages();
      this.logger.log({ count: discoveredPages.length, msg: 'Discovery completed' });

      const diffResult = await this.fileDiffService.computeDiff(discoveredPages);

      const pageIdsToFetch = new Set([...diffResult.newPageIds, ...diffResult.updatedPageIds]);

      if (pageIdsToFetch.size > 0) {
        const pagesToFetch = discoveredPages.filter((p) => pageIdsToFetch.has(p.id));

        const spaceKeys = [...new Set(pagesToFetch.map((p) => p.spaceKey))];
        const spaceScopes = await this.scopeManagementService.ensureSpaceScopes(
          rootScopePath,
          spaceKeys,
        );

        await this.fetchAndIngestPages(
          pagesToFetch,
          spaceScopes,
          tenant.config.processing.concurrency,
        );
      }

      if (diffResult.deletedPageIds.length > 0) {
        await this.ingestionService.deleteContentByKeys(diffResult.deletedPageIds);
        this.logger.log({
          count: diffResult.deletedPageIds.length,
          msg: 'Deleted content processed',
        });
      }

      this.logger.log({ msg: 'Sync work done' });
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

    if (pages.length === 0) {
      this.logger.log({ msg: 'No pages to ingest' });
      return;
    }

    const results = await Promise.allSettled(
      pages.map((page) =>
        limit(async () => {
          const fetched = await this.contentFetcher.fetchPageContent(page);

          if (!fetched) {
            return;
          }
          const scopeId = spaceScopes.get(page.spaceKey);
          assert.ok(scopeId, `No scope resolved for space: ${page.spaceKey}`);
          await this.ingestionService.ingestPage(fetched, scopeId);
        }),
      ),
    );

    for (const result of results) {
      if (result.status === 'rejected') {
        this.logger.error({ err: result.reason, msg: 'Page ingestion failed' });
      }
    }
  }
}
