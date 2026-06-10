import assert from 'node:assert';
import { elapsedSeconds } from '@unique-ag/utils';
import { Logger } from '@nestjs/common';
import pLimit from 'p-limit';
import type { SyncResult } from '../health/sync-result.types';
import { type Metrics, SyncPhase } from '../metrics';
import { getCurrentTenant } from '../tenant';
import type { ConfluenceContentFetcher } from './confluence-content-fetcher';
import type { ConfluencePageScanner } from './confluence-page-scanner';
import type { FileDiffService } from './file-diff.service';
import type { IngestionService } from './ingestion.service';
import { isImageMimeType } from './mime-type';
import { buildInlinedAttachmentKey, type PageImageInliner } from './page-image-inliner';
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
    private readonly pageImageInliner: PageImageInliner,
    private readonly scopeManagementService: ScopeManagementService,
    private readonly metrics: Metrics,
  ) {}

  public async synchronize(): Promise<SyncResult> {
    const tenant = getCurrentTenant();

    if (tenant.isScanning) {
      this.logger.log({
        tenantName: tenant.name,
        msg: 'Sync already in progress, skipping',
      });
      return { status: 'skipped', reason: 'sync_in_progress' };
    }

    tenant.isScanning = true;
    const startTime = Date.now();
    let syncResult: 'success' | 'failure' = 'success';
    // The inliner caches "list attachments of page X in space Y" lookups (used when
    // an image references an attachment on a different page). Clear it each sync so
    // attachment changes on those referenced pages are picked up next run.
    this.pageImageInliner.resetOtherPageAttachmentCache();

    try {
      this.logger.log({ tenantName: tenant.name, msg: 'Starting sync' });

      this.metrics.setSyncPhase(SyncPhase.Scanning);
      const rootScopePath = await this.scopeManagementService.initialize();

      const scanStartTime = Date.now();
      const { pages: discoveredPages, attachments: discoveredAttachments } =
        await this.scanner.discoverPages();
      this.metrics.recordScanDuration(elapsedSeconds(scanStartTime));
      this.logger.log({
        count: discoveredPages.length,
        msg: 'Discovery completed',
      });

      this.metrics.setSyncPhase(SyncPhase.Diffing);
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
        this.metrics.recordSyncItemTotals(pagesToFetch.length, attachmentsToIngest.length);

        const spaceKeys = [
          ...new Set([
            ...pagesToFetch.map((p) => p.spaceKey),
            // include attachment space keys for completeness and possible edge cases
            ...attachmentsToIngest.map((a) => a.spaceKey),
          ]),
        ];
        const spaceScopes = await this.scopeManagementService.ensureSpaceScopes(
          rootScopePath,
          spaceKeys,
          allSpaceKeyToSpaceId,
        );

        const concurrency = tenant.config.processing.concurrency;
        const imageAttachmentsByPageId =
          this.buildImageAttachmentsByPageIdMap(discoveredAttachments);
        const inlinedAttachmentIds = new Set<string>();

        this.metrics.setSyncPhase(SyncPhase.IngestingPages);
        await this.fetchAndIngestPages(
          pagesToFetch,
          spaceScopes,
          concurrency,
          imageAttachmentsByPageId,
          inlinedAttachmentIds,
        );

        const remainingAttachments = attachmentsToIngest.filter(
          (a) => !inlinedAttachmentIds.has(buildInlinedAttachmentKey(a.pageId, a.id)),
        );

        this.metrics.setSyncPhase(SyncPhase.IngestingAttachments);
        await this.ingestAttachments(remainingAttachments, spaceScopes, concurrency);
      }

      if (diffResult.deletedItems.length > 0) {
        this.metrics.setSyncPhase(SyncPhase.Deleting);
        const contentKeys = diffResult.deletedItems.map((item) => `${item.partialKey}/${item.id}`);
        const deletedCount = await this.ingestionService.deleteContentByKeys(contentKeys);
        this.logger.log({
          requested: diffResult.deletedItems.length,
          deleted: deletedCount,
          msg: 'Deleted content processed',
        });
      }

      this.metrics.setSyncPhase(SyncPhase.CleaningUp);
      await this.scopeManagementService.cleanupRemovedSpaces(new Set(allSpaceKeyToSpaceId.keys()));

      this.logger.log({ msg: 'Sync work done' });
      return { status: 'success' };
    } catch (err) {
      syncResult = 'failure';
      this.logger.error({ err, msg: 'Sync failed' });
      return { status: 'failure' };
    } finally {
      tenant.isScanning = false;
      this.metrics.setSyncPhase(SyncPhase.Idle);
      this.metrics.recordSyncDuration(elapsedSeconds(startTime), syncResult);
    }
  }

  private async fetchAndIngestPages(
    pages: DiscoveredPage[],
    spaceScopes: Map<string, string>,
    concurrency: number,
    imageAttachmentsByPageId: Map<string, DiscoveredAttachment[]>,
    inlinedAttachmentIds: Set<string>,
  ): Promise<void> {
    const limit = pLimit(concurrency);

    if (pages.length === 0) {
      this.logger.log({ msg: 'No pages to ingest' });
      return;
    }

    let processed = 0;
    let ingested = 0;
    let skipped = 0;
    const total = pages.length;

    await Promise.allSettled(
      pages.map((page) =>
        limit(async () => {
          const fetched = await this.contentFetcher.fetchPageContent(page);

          if (!fetched) {
            skipped++;
            this.metrics.recordPagesProcessed(1, 'skipped');
            return;
          }
          const scopeId = spaceScopes.get(page.spaceKey);
          assert.ok(scopeId, `No scope resolved for space: ${page.spaceKey}`);
          const pageImageAttachments = imageAttachmentsByPageId.get(page.id) ?? [];
          let pageToIngest = fetched;
          try {
            const inlined = await this.pageImageInliner.inlineImages(fetched, pageImageAttachments);
            pageToIngest = inlined.page;
            for (const id of inlined.inlinedAttachmentIds) {
              inlinedAttachmentIds.add(id);
            }
          } catch (err) {
            // A hard failure inside the inliner must not lose the page. Fall back to ingesting the original body;
            // the standalone attachment pass will still handle the images.
            this.logger.warn({
              pageId: page.id,
              err,
              msg: 'Image inliner threw, ingesting original body',
            });
          }
          await this.ingestionService.ingestPage(pageToIngest, scopeId);
          ingested++;
          this.metrics.recordPagesProcessed(1, 'success');
        })
          .catch((err) => {
            this.metrics.recordPagesProcessed(1, 'failure');
            throw err;
          })
          .finally(() => {
            processed++;
            if (processed % INGESTION_PROGRESS_LOG_INTERVAL === 0) {
              this.logger.log({
                processed,
                total,
                msg: 'Page ingestion in progress',
              });
            }
          }),
      ),
    );

    const failed = pages.length - ingested - skipped;

    this.logger.log({
      total: pages.length,
      ingested,
      skipped,
      failed,
      msg: 'Page ingestion summary',
    });
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

    let ingested = 0;

    await Promise.allSettled(
      attachments.map((attachment) =>
        limit(async () => {
          const scopeId = spaceScopes.get(attachment.spaceKey);
          assert.ok(scopeId, `No scope resolved for space: ${attachment.spaceKey}`);
          await this.ingestionService.ingestAttachment(attachment, scopeId);
          ingested++;
          this.metrics.recordAttachmentsProcessed(1, 'success');
        })
          .catch((err) => {
            this.metrics.recordAttachmentsProcessed(1, 'failure');
            throw err;
          })
          .finally(() => {
            processed++;
            if (processed % INGESTION_PROGRESS_LOG_INTERVAL === 0) {
              this.logger.log({
                processed,
                total,
                msg: 'Attachment ingestion in progress',
              });
            }
          }),
      ),
    );

    const failed = attachments.length - ingested;

    this.logger.log({
      total: attachments.length,
      ingested,
      failed,
      msg: 'Attachment ingestion summary',
    });
  }

  private buildImageAttachmentsByPageIdMap(
    attachments: DiscoveredAttachment[],
  ): Map<string, DiscoveredAttachment[]> {
    const map = new Map<string, DiscoveredAttachment[]>();
    for (const attachment of attachments) {
      if (!isImageMimeType(attachment.mediaType)) {
        continue;
      }
      const existing = map.get(attachment.pageId);
      if (existing) {
        existing.push(attachment);
      } else {
        map.set(attachment.pageId, [attachment]);
      }
    }
    return map;
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
}
