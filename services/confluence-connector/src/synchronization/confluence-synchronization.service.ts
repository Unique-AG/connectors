import assert from 'node:assert';
import { Logger } from '@nestjs/common';
import pLimit from 'p-limit';
import { getCurrentTenant } from '../tenant';
import type { ConfluenceContentFetcher } from './confluence-content-fetcher';
import type { ConfluencePageScanner } from './confluence-page-scanner';
import type { FileDiffService } from './file-diff.service';
import type { IngestionService } from './ingestion.service';
import type { ScopeManagementService } from './scope-management.service';
import type { DiscoveredAttachment, DiscoveredPage } from './sync.types';

const INGESTION_PROGRESS_LOG_INTERVAL = 100;

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

      const { pages: discoveredPages, attachments: discoveredAttachments } =
        await this.scanner.discoverPages();
      this.logger.log({ count: discoveredPages.length, msg: 'Discovery completed' });

      const allSpaceKeyToSpaceId = this.buildSpaceKeyToSpaceIdMap(
        discoveredPages,
        discoveredAttachments,
      );

      const diffResult = await this.fileDiffService.computeDiff(
        discoveredPages,
        discoveredAttachments,
      );

      const itemIdsToProcess = new Set([...diffResult.newItemIds, ...diffResult.updatedItemIds]);
      const pagesToFetch = discoveredPages.filter((p) => itemIdsToProcess.has(p.id));
      const attachmentsToIngest = discoveredAttachments.filter((a) =>
        itemIdsToProcess.has(`${a.pageId}::${a.id}`),
      );

      if (pagesToFetch.length > 0 || attachmentsToIngest.length > 0) {
        const spaceKeys = [
          ...new Set([
            ...pagesToFetch.map((p) => p.spaceKey),
            ...attachmentsToIngest.map((a) => a.spaceKey),
          ]),
        ];
        const spaceScopes = await this.scopeManagementService.ensureSpaceScopes(
          rootScopePath,
          spaceKeys,
          allSpaceKeyToSpaceId,
        );

        const concurrency = tenant.config.processing.concurrency;
        await this.fetchAndIngestPages(pagesToFetch, spaceScopes, concurrency);
        await this.ingestAttachments(attachmentsToIngest, spaceScopes, concurrency);
      }

      if (diffResult.deletedItems.length > 0) {
        const contentKeys = diffResult.deletedItems.map((item) => `${item.partialKey}/${item.id}`);
        const deletedCount = await this.ingestionService.deleteContentByKeys(contentKeys);
        this.logger.log({
          requested: diffResult.deletedItems.length,
          deleted: deletedCount,
          msg: 'Deleted content processed',
        });
      }

      await this.scopeManagementService.cleanupRemovedSpaces(new Set(allSpaceKeyToSpaceId.keys()));

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

    let processed = 0;
    const total = pages.length;

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
        }).finally(() => {
          processed++;
          if (processed % INGESTION_PROGRESS_LOG_INTERVAL === 0) {
            this.logger.log({ processed, total, msg: 'Page ingestion in progress' });
          }
        }),
      ),
    );

    this.logSettledResults(results, 'Page ingestion summary');
  }

  private async ingestAttachments(
    attachments: DiscoveredAttachment[],
    spaceScopes: Map<string, string>,
    concurrency: number,
  ): Promise<void> {
    if (attachments.length === 0) {
      return;
    }

    const limit = pLimit(concurrency);
    let processed = 0;
    const total = attachments.length;

    const results = await Promise.allSettled(
      attachments.map((attachment) =>
        limit(async () => {
          const scopeId = spaceScopes.get(attachment.spaceKey);
          assert.ok(scopeId, `No scope resolved for space: ${attachment.spaceKey}`);
          await this.ingestionService.ingestAttachment(attachment, scopeId);
        }).finally(() => {
          processed++;
          if (processed % INGESTION_PROGRESS_LOG_INTERVAL === 0) {
            this.logger.log({ processed, total, msg: 'Attachment ingestion in progress' });
          }
        }),
      ),
    );

    this.logSettledResults(results, 'Attachment ingestion summary');
  }

  private buildSpaceKeyToSpaceIdMap(
    pages: DiscoveredPage[],
    attachments: DiscoveredAttachment[],
  ): Map<string, string> {
    const map = new Map<string, string>();
    for (const page of pages) {
      map.set(page.spaceKey, page.spaceId);
    }
    for (const attachment of attachments) {
      map.set(attachment.spaceKey, attachment.spaceId);
    }
    return map;
  }

  private logSettledResults(results: PromiseSettledResult<void>[], msg: string): void {
    const succeeded = results.filter((r) => r.status === 'fulfilled').length;
    const failed = results.filter((r) => r.status === 'rejected').length;
    this.logger.log({ total: results.length, succeeded, failed, msg });
  }
}
