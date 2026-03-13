import { createSmeared } from '@unique-ag/utils';
import { Logger } from '@nestjs/common';
import type { ConfluenceConfig, ProcessingConfig } from '../config';
import { type AttachmentConfig, BYTES_PER_MB } from '../config/ingestion.schema';
import type { ConfluenceAttachment, ConfluencePage } from '../confluence-api';
import { type ConfluenceApiClient, ContentType } from '../confluence-api';
import type { DiscoveredAttachment, DiscoveredPage, DiscoveryResult } from './sync.types';

const SKIPPED_CONTENT_TYPES = [
  ContentType.DATABASE,
  ContentType.BLOGPOST,
  ContentType.WHITEBOARD,
  ContentType.EMBED,
];

export class ConfluencePageScanner {
  private readonly logger = new Logger(ConfluencePageScanner.name);

  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly processingConfig: ProcessingConfig,
    private readonly apiClient: ConfluenceApiClient,
    private readonly attachmentConfig: AttachmentConfig,
  ) {}

  public async discoverPages(): Promise<DiscoveryResult> {
    const seenPageIds = new Set<string>();
    const allRawPages: ConfluencePage[] = [];

    const labeledPages = await this.apiClient.searchPagesByLabel();
    allRawPages.push(...labeledPages);
    const discoveredPages = this.mapToDiscoveredPages(labeledPages, seenPageIds);

    const ingestAllRootPageIds = labeledPages
      .filter((page) => this.hasIngestAllLabel(page))
      .map((page) => page.id);

    if (ingestAllRootPageIds.length > 0) {
      const descendants = await this.apiClient.getDescendantPages(ingestAllRootPageIds);
      allRawPages.push(...descendants);
      discoveredPages.push(...this.mapToDiscoveredPages(descendants, seenPageIds));
    }

    this.logger.log({ count: discoveredPages.length, msg: 'Page discovery completed' });

    // Attachments are already present on page objects from the expand=children.attachment
    // parameter in searchPagesByLabel/getDescendantPages. We just extract and filter them here.
    const filteredRawPages = allRawPages.filter((p) => seenPageIds.has(p.id));
    const attachments = this.attachmentConfig.mode
      ? this.extractDiscoveredAttachments(filteredRawPages)
      : [];

    if (this.attachmentConfig.mode) {
      this.logger.log({ count: attachments.length, msg: 'Attachment discovery completed' });
    }

    return { pages: discoveredPages, attachments };
  }

  private mapToDiscoveredPages(
    pages: ConfluencePage[],
    seenPageIds: Set<string>,
  ): DiscoveredPage[] {
    const discoveredPages: DiscoveredPage[] = [];

    for (const page of pages) {
      if (this.isLimitReached(seenPageIds.size)) {
        break;
      }

      if (SKIPPED_CONTENT_TYPES.includes(page.type)) {
        this.logger.debug({
          pageId: page.id,
          title: createSmeared(page.title),
          type: page.type,
          msg: 'Skipping non-page content type',
        });
        continue;
      }

      if (seenPageIds.has(page.id)) {
        continue;
      }

      seenPageIds.add(page.id);

      discoveredPages.push({
        id: page.id,
        title: page.title,
        type: page.type,
        spaceId: page.space.id,
        spaceKey: page.space.key,
        spaceName: page.space.name,
        versionTimestamp: page.version.when,
        webUrl: this.apiClient.buildPageWebUrl(page),
        labels: page.metadata.labels.results.map((label) => label.name),
      });
    }

    return discoveredPages;
  }

  /**
   * Extracts attachments from already-fetched page objects. The raw Confluence pages
   * contain attachment data from the `expand=children.attachment` parameter —
   * no additional API requests are made here.
   */
  private extractDiscoveredAttachments(rawPages: ConfluencePage[]): DiscoveredAttachment[] {
    const allAttachments: DiscoveredAttachment[] = [];
    let remainingCapacity = this.remainingCapacity(rawPages.length);

    for (const page of rawPages) {
      const results = page.children?.attachment?.results;
      if (!results || results.length === 0) {
        continue;
      }

      const webUrl = this.apiClient.buildPageWebUrl(page);

      for (const attachment of results) {
        if (remainingCapacity <= 0) {
          return allAttachments;
        }

        if (!this.isAttachmentAllowed(attachment)) {
          continue;
        }

        allAttachments.push({
          id: attachment.id,
          title: attachment.title,
          mediaType: attachment.extensions.mediaType,
          fileSize: attachment.extensions.fileSize,
          downloadPath: attachment._links.download,
          versionTimestamp: attachment.version?.when ?? page.version.when,
          pageId: page.id,
          spaceId: page.space.id,
          spaceKey: page.space.key,
          spaceName: page.space.name,
          webUrl,
        });

        remainingCapacity--;
      }
    }

    return allAttachments;
  }

  private isAttachmentAllowed(attachment: ConfluenceAttachment): boolean {
    const maxFileSizeBytes = this.attachmentConfig.maxFileSizeMb * BYTES_PER_MB;
    if (attachment.extensions.fileSize > maxFileSizeBytes) {
      this.logger.debug({
        attachmentId: attachment.id,
        title: createSmeared(attachment.title),
        fileSize: attachment.extensions.fileSize,
        maxFileSizeMb: this.attachmentConfig.maxFileSizeMb,
        msg: 'Attachment exceeds max file size',
      });
      return false;
    }

    const extension = this.extractExtension(attachment.title);
    if (!extension || !this.attachmentConfig.allowedExtensions.includes(extension)) {
      this.logger.debug({
        attachmentId: attachment.id,
        title: createSmeared(attachment.title),
        extension,
        msg: 'Attachment extension not allowed',
      });
      return false;
    }

    return true;
  }

  private extractExtension(filename: string): string | undefined {
    const lastDot = filename.lastIndexOf('.');
    if (lastDot === -1 || lastDot === filename.length - 1) {
      return undefined;
    }
    return filename.slice(lastDot + 1).toLowerCase();
  }

  private hasIngestAllLabel(page: ConfluencePage): boolean {
    return page.metadata.labels.results.some(
      (label) => label.name === this.confluenceConfig.ingestAllLabel,
    );
  }

  private isLimitReached(currentCount: number): boolean {
    const limit = this.processingConfig.maxItemsToScan;
    if (limit === undefined) {
      return false;
    }
    if (currentCount >= limit) {
      this.logger.log({ limit, msg: 'maxItemsToScan limit reached' });
      return true;
    }
    return false;
  }

  private remainingCapacity(currentCount: number): number {
    const limit = this.processingConfig.maxItemsToScan;
    if (limit === undefined) {
      return Infinity;
    }
    return Math.max(0, limit - currentCount);
  }
}
