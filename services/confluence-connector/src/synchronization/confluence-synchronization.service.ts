import assert from 'node:assert';
import { elapsedSeconds } from '@unique-ag/utils';
import { Logger } from '@nestjs/common';
import pLimit from 'p-limit';
import { groupBy } from 'remeda';
import type { SyncResult } from '../health/sync-result.types';
import { type Metrics, SyncPhase } from '../metrics';
import { getCurrentTenant } from '../tenant';
import type { ConfluenceContentFetcher } from './confluence-content-fetcher';
import type { ConfluencePageScanner } from './confluence-page-scanner';
import type { FileDiffService } from './file-diff.service';
import type { IngestionService } from './ingestion.service';
import { isImageMimeType } from './mime-type';
import type { PageImageInliner } from './page-image-inliner';
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

      // we either inline images in the page, either ingest them separately with no inlining.
      // when inlining we must exclude them from file-diff else we will ingest them twice: inlined and as attachment.
      const trackedAttachments = tenant.config.ingestion.attachments.inlineImagesEnabled
        ? discoveredAttachments.filter((a) => !isImageMimeType(a.mediaType))
        : discoveredAttachments;

      const diffResult = await this.fileDiffService.computeDiff(
        discoveredPages,
        trackedAttachments,
      );

      const itemIdsToProcess = new Set([...diffResult.newItemIds, ...diffResult.updatedItemIds]);
      const pagesToFetch = discoveredPages.filter((p) => itemIdsToProcess.has(p.id));

      const attachmentsToIngest = trackedAttachments.filter((discoveredAttachment) =>
        itemIdsToProcess.has(`${discoveredAttachment.pageId}::${discoveredAttachment.id}`),
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

        const imageAttachmentsByPageId = groupBy(
          discoveredAttachments.filter((a) => isImageMimeType(a.mediaType)),
          (a) => a.pageId,
        );

        this.metrics.setSyncPhase(SyncPhase.IngestingPages);
        await this.fetchAndIngestPages(
          pagesToFetch,
          spaceScopes,
          tenant.config.processing.concurrency,
          imageAttachmentsByPageId,
        );

        this.metrics.setSyncPhase(SyncPhase.IngestingAttachments);
        await this.ingestAttachments(
          attachmentsToIngest,
          spaceScopes,
          tenant.config.processing.concurrency,
        );
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
    imageAttachmentsByPageId: Readonly<Partial<Record<string, DiscoveredAttachment[]>>>,
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

          const pageImageAttachments = imageAttachmentsByPageId[page.id] ?? [];
          let pageToIngest = fetched;

          try {
            pageToIngest = await this.pageImageInliner.inlineImagesInPage(fetched, pageImageAttachments);
          } catch (err) {
            // A hard failure inside the inliner must not lose the page; ingest the original body.
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

    const total = attachments.length;
    this.logger.log({ total, msg: 'Starting attachment ingestion' });

    const limit = pLimit(concurrency);
    let processed = 0;

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
