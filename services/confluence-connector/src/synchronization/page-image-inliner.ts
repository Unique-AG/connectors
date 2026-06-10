import assert from 'node:assert';
import { Logger } from '@nestjs/common';
import { indexBy } from 'remeda';
import type { TenantConfig } from '../config';
import { BYTES_PER_MB } from '../config/ingestion.schema';
import type {
  ConfluenceApiClient,
  ConfluenceAttachment,
  PageAttachmentLookupResult,
} from '../confluence-api';
import {
  type ParsedImageMacro,
  parseImageBlocks,
  type ResourceRef,
} from './confluence-tags-parser';
import { isImageMimeType, normalizeMimeType } from './mime-type';
import type { DiscoveredAttachment, FetchedPage } from './sync.types';

// ac:image attributes forwarded onto <img>; presentational hints (align, thumbnail, etc.) are dropped.
const AC_IMAGE_ATTRS_TO_KEEP: ReadonlyArray<[string, string]> = [
  ['ac:title', 'title'],
  ['ac:width', 'width'],
  ['ac:height', 'height'],
];

export interface InlineImagesResult {
  page: FetchedPage;
  inlinedAttachmentIds: Set<string>;
}

interface ResolvedAttachment {
  attachmentId: string;
  pageId: string;
  downloadPath: string;
  mediaType: string;
  fileSize: number;
  filename: string;
}

interface ImageReplacement {
  start: number;
  end: number;
  attachmentId: string;
  pageId: string;
  html: string;
}

// Keyed by ${pageId}::${attachmentId} since attachment ids aren't globally unique across pages.
export function buildInlinedAttachmentKey(pageId: string, attachmentId: string): string {
  return `${pageId}::${attachmentId}`;
}

export class PageImageInliner {
  private readonly logger = new Logger(PageImageInliner.name);
  // Caches "list attachments of page <title> in space <key>" lookups, used when an image
  // macro references an attachment on a different page. Per-sync only; the orchestrator
  // calls resetOtherPageAttachmentCache() at the start of each sync so attachment changes
  // on referenced pages are picked up on the next run.
  private readonly otherPageAttachmentCache = new Map<
    string,
    Promise<PageAttachmentLookupResult | null>
  >();

  public constructor(
    private readonly config: TenantConfig,
    private readonly confluenceApiClient: ConfluenceApiClient,
  ) {}

  public resetOtherPageAttachmentCache(): void {
    this.otherPageAttachmentCache.clear();
  }

  public async inlineImages(
    page: FetchedPage,
    pageImageAttachments: DiscoveredAttachment[],
  ): Promise<InlineImagesResult> {
    if (!page.body) {
      return { page, inlinedAttachmentIds: new Set() };
    }

    const blocks = parseImageBlocks(page.body);
    if (blocks.length === 0) {
      return { page, inlinedAttachmentIds: new Set() };
    }

    const pageImageAttachmentsByTitle = indexBy(pageImageAttachments, (a) => a.title);
    const replacements = await Promise.all(
      blocks.map((block) =>
        this.buildImageReplacement(block, page, pageImageAttachmentsByTitle).catch((err) => {
          this.logger.warn({
            pageId: page.id,
            resource: block.resourceRef,
            err,
            msg: 'Failed to inline image, leaving macro untouched',
          });
          return null;
        }),
      ),
    );

    const inlinedAttachmentIds = new Set<string>();
    const successfulReplacements: ImageReplacement[] = [];

    for (const replacement of replacements) {
      if (!replacement) {
        continue;
      }
      successfulReplacements.push(replacement);
      inlinedAttachmentIds.add(
        buildInlinedAttachmentKey(replacement.pageId, replacement.attachmentId),
      );
    }

    if (successfulReplacements.length === 0) {
      return { page, inlinedAttachmentIds: new Set() };
    }

    const newBody = this.applyReplacements(page.body, successfulReplacements);
    return {
      page: { ...page, body: newBody },
      inlinedAttachmentIds,
    };
  }

  private async buildImageReplacement(
    block: ParsedImageMacro,
    page: FetchedPage,
    pageImageAttachmentsByTitle: Readonly<Record<string, DiscoveredAttachment>>,
  ): Promise<ImageReplacement | null> {
    const resolved = await this.resolveAttachmentMetadata(
      block.resourceRef,
      page,
      pageImageAttachmentsByTitle,
    );
    if (!resolved) {
      return null;
    }

    if (!isImageMimeType(resolved.mediaType)) {
      this.logger.debug({
        pageId: page.id,
        filename: resolved.filename,
        mediaType: resolved.mediaType,
        msg: 'Referenced attachment is not an image, leaving macro untouched',
      });
      return null;
    }

    // Other-page lookups bypass discovery's allowedMimeTypes filter; re-check here.
    if (!this.isAllowedMimeType(resolved.mediaType)) {
      this.logger.debug({
        pageId: page.id,
        filename: resolved.filename,
        mediaType: resolved.mediaType,
        msg: 'Referenced image MIME type is not in allowedMimeTypes, leaving macro untouched',
      });
      return null;
    }

    if (this.exceedsMaxSize(resolved.fileSize)) {
      this.logger.warn({
        pageId: page.id,
        filename: resolved.filename,
        fileSize: resolved.fileSize,
        maxFileSizeMb: this.config.ingestion.attachments.maxFileSizeMb,
        msg: 'Image exceeds max file size, leaving macro untouched',
      });
      return null;
    }

    const buffer = await this.downloadToBuffer(
      resolved.attachmentId,
      resolved.pageId,
      resolved.downloadPath,
    );
    const html = this.buildImgTag(block.imgAttrs, resolved.mediaType, buffer, resolved.filename);
    return {
      start: block.startIndex,
      end: block.endIndex,
      attachmentId: resolved.attachmentId,
      pageId: resolved.pageId,
      html,
    };
  }

  private async resolveAttachmentMetadata(
    resource: ResourceRef,
    page: FetchedPage,
    pageImageAttachmentsByTitle: Readonly<Record<string, DiscoveredAttachment>>,
  ): Promise<ResolvedAttachment | null> {
    if (resource.kind === 'current-attachment') {
      return this.resolveCurrentPageAttachment(resource, page, pageImageAttachmentsByTitle);
    }

    if (resource.kind === 'other-page-attachment') {
      return this.resolveOtherPageAttachment(resource);
    }

    return null;
  }

  private resolveCurrentPageAttachment(
    resource: Extract<ResourceRef, { kind: 'current-attachment' }>,
    page: FetchedPage,
    pageImageAttachmentsByTitle: Readonly<Record<string, DiscoveredAttachment>>,
  ): ResolvedAttachment | null {
    const match = pageImageAttachmentsByTitle[resource.filename];
    if (!match) {
      this.logger.debug({
        pageId: page.id,
        filename: resource.filename,
        msg: 'Image filename not found among page attachments',
      });
      return null;
    }
    return this.fromDiscoveredAttachment(match);
  }

  private async resolveOtherPageAttachment(
    resource: Extract<ResourceRef, { kind: 'other-page-attachment' }>,
  ): Promise<ResolvedAttachment | null> {
    const lookup = await this.lookupOtherPageAttachments(resource.spaceKey, resource.contentTitle);
    if (!lookup) {
      this.logger.debug({
        spaceKey: resource.spaceKey,
        contentTitle: resource.contentTitle,
        msg: 'Referenced page not found when resolving image on another page',
      });
      return null;
    }
    const match = lookup.attachments.find(
      (a: ConfluenceAttachment) => a.title === resource.filename,
    );
    if (!match) {
      this.logger.debug({
        spaceKey: resource.spaceKey,
        contentTitle: resource.contentTitle,
        filename: resource.filename,
        msg: 'Image filename not found on referenced other page',
      });
      return null;
    }
    return this.fromConfluenceAttachment(match, lookup.pageId);
  }

  private fromDiscoveredAttachment(attachment: DiscoveredAttachment): ResolvedAttachment {
    return {
      attachmentId: attachment.id,
      pageId: attachment.pageId,
      downloadPath: attachment.downloadPath,
      mediaType: attachment.mediaType,
      fileSize: attachment.fileSize,
      filename: attachment.title,
    };
  }

  private fromConfluenceAttachment(
    attachment: ConfluenceAttachment,
    pageId: string,
  ): ResolvedAttachment {
    return {
      attachmentId: attachment.id,
      pageId,
      downloadPath: attachment._links.download,
      mediaType: attachment.extensions.mediaType,
      fileSize: attachment.extensions.fileSize,
      filename: attachment.title,
    };
  }

  private async lookupOtherPageAttachments(
    spaceKey: string,
    contentTitle: string,
  ): Promise<PageAttachmentLookupResult | null> {
    // JSON.stringify avoids separator collisions that a plain concatenation would create.
    const cacheKey = JSON.stringify([spaceKey, contentTitle]);
    const cached = this.otherPageAttachmentCache.get(cacheKey);
    if (cached) {
      return cached;
    }
    const promise = this.confluenceApiClient
      .fetchPageAttachmentsByTitle(spaceKey, contentTitle)
      .catch((err) => {
        // Don't cache errors permanently; a legitimate null (404) stays cached.
        this.otherPageAttachmentCache.delete(cacheKey);
        this.logger.warn({
          spaceKey,
          contentTitle,
          err,
          msg: 'Attachment lookup on referenced other page failed',
        });
        return null;
      });
    this.otherPageAttachmentCache.set(cacheKey, promise);
    return promise;
  }

  private isAllowedMimeType(mimeType: string): boolean {
    return this.config.ingestion.attachments.allowedMimeTypes.includes(normalizeMimeType(mimeType));
  }

  private exceedsMaxSize(fileSize: number): boolean {
    const maxBytes = this.config.ingestion.attachments.maxFileSizeMb * BYTES_PER_MB;
    return fileSize > maxBytes;
  }

  private async downloadToBuffer(
    attachmentId: string,
    pageId: string,
    downloadPath: string,
  ): Promise<Buffer> {
    const stream = await this.confluenceApiClient.getAttachmentDownloadStream(
      attachmentId,
      pageId,
      downloadPath,
    );
    const chunks: Buffer[] = [];
    for await (const chunk of stream) {
      chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    }
    return Buffer.concat(chunks);
  }

  private buildImgTag(
    imgAttrs: Record<string, string>,
    mimeType: string,
    buffer: Buffer,
    filename: string,
  ): string {
    const base64 = buffer.toString('base64');
    const normalizedMimeType = normalizeMimeType(mimeType);
    const altValue = imgAttrs['ac:alt'] ?? filename;

    const parts: string[] = [`src="data:${normalizedMimeType};base64,${base64}"`];
    if (altValue) {
      parts.push(`alt="${escapeAttr(altValue)}"`);
    }
    for (const [acAttr, htmlAttr] of AC_IMAGE_ATTRS_TO_KEEP) {
      const value = imgAttrs[acAttr];
      if (value === undefined) {
        continue;
      }
      parts.push(`${htmlAttr}="${escapeAttr(value)}"`);
    }
    return `<img ${parts.join(' ')} />`;
  }

  private applyReplacements(
    original: string,
    replacements: Array<{ start: number; end: number; html: string }>,
  ): string {
    const sorted = [...replacements].sort((a, b) => a.start - b.start);
    let result = '';
    let cursor = 0;
    for (const r of sorted) {
      assert.ok(r.start >= cursor, 'image-block replacements must not overlap');
      result += original.slice(cursor, r.start) + r.html;
      cursor = r.end;
    }
    result += original.slice(cursor);
    return result;
  }
}

function escapeAttr(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}
