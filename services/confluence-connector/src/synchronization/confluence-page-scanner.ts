import { Logger } from '@nestjs/common';
import { createSmeared } from '@unique-ag/utils';
import type { ConfluenceConfig, ProcessingConfig } from '../config';
import { BYTES_PER_MB, type AttachmentConfig } from '../config/ingestion.schema';
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
    const allAttachments: DiscoveredAttachment[] = [];
    const labeledPages = await this.apiClient.searchPagesByLabel();
    const discoveredPages = this.mapToDiscoveredPages(labeledPages, seenPageIds, allAttachments);

    const ingestAllRootPageIds = labeledPages
      .filter((page) => this.hasIngestAllLabel(page))
      .map((page) => page.id);

    if (ingestAllRootPageIds.length > 0) {
      // we are fetching descendants on content marked with ai-ingest-all label regardless of the content type
      const descendants = await this.apiClient.getDescendantPages(ingestAllRootPageIds);
      const mappedDescendantPages = this.mapToDiscoveredPages(descendants, seenPageIds, allAttachments);
      discoveredPages.push(...mappedDescendantPages);
    }

    this.logger.log({ count: discoveredPages.length, msg: 'Page discovery completed' });
    if (allAttachments.length > 0) {
      this.logger.log({ count: allAttachments.length, msg: 'Attachments discovered' });
    }
    return { pages: discoveredPages, attachments: allAttachments };
  }

  private mapToDiscoveredPages(
    pages: ConfluencePage[],
    seenPageIds: Set<string>,
    allAttachments: DiscoveredAttachment[],
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

      const webUrl = this.apiClient.buildPageWebUrl(page);

      discoveredPages.push({
        id: page.id,
        title: page.title,
        type: page.type,
        spaceId: page.space.id,
        spaceKey: page.space.key,
        spaceName: page.space.name,
        versionTimestamp: page.version.when,
        webUrl,
        labels: page.metadata.labels.results.map((label) => label.name),
      });

      if (this.attachmentConfig.enabled && page.children?.attachment) {
        const attachments = this.extractAttachments(page, webUrl);
        allAttachments.push(...attachments);
      }
    }

    return discoveredPages;
  }

  private extractAttachments(page: ConfluencePage, pageWebUrl: string): DiscoveredAttachment[] {
    const results = page.children?.attachment?.results;
    if (!results || results.length === 0) {
      return [];
    }

    const attachments: DiscoveredAttachment[] = [];
    for (const attachment of results) {
      if (!this.isAttachmentAllowed(attachment)) {
        continue;
      }

      attachments.push({
        id: attachment.id,
        title: attachment.title,
        mediaType: attachment.extensions.mediaType,
        fileSize: attachment.extensions.fileSize,
        downloadPath: attachment._links.download,
        versionTimestamp: attachment.version?.when,
        pageId: page.id,
        spaceId: page.space.id,
        spaceKey: page.space.key,
        spaceName: page.space.name,
        webUrl: pageWebUrl,
      });
    }

    return attachments;
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
    const limit = this.processingConfig.maxPagesToScan;
    if (limit === undefined) {
      return false;
    }
    if (currentCount >= limit) {
      this.logger.log({ limit, msg: 'maxPagesToScan limit reached' });
      return true;
    }
    return false;
  }
}
