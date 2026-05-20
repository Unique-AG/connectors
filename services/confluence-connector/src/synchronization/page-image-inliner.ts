import assert from 'node:assert';
import { Logger } from '@nestjs/common';
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
import { isImageMediaType } from './media-type';
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

// Keyed by ${pageId}::${attachmentId} since attachment ids aren't globally unique across pages.
export function buildInlinedAttachmentKey(pageId: string, attachmentId: string): string {
  return `${pageId}::${attachmentId}`;
}

export class PageImageInliner {
  private readonly logger = new Logger(PageImageInliner.name);
  // Per-sync cache; orchestrator calls resetCrossPageCache() at the start of each sync.
  private readonly crossPageCache = new Map<string, Promise<PageAttachmentLookupResult | null>>();

  public constructor(
    private readonly config: TenantConfig,
    private readonly confluenceApiClient: ConfluenceApiClient,
  ) {}

  public resetCrossPageCache(): void {
    this.crossPageCache.clear();
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

    const replacements = await Promise.all(
      blocks.map((block) =>
        this.buildImageReplacement(block, page, pageImageAttachments).catch((err) => {
          this.logger.warn({
            pageId: page.id,
            resource: block.resource,
            err,
            msg: 'Failed to inline image, leaving macro untouched',
          });
          return null;
        }),
      ),
    );

    const inlinedAttachmentIds = new Set<string>();
    const splicePoints: Array<{ start: number; end: number; html: string }> = [];

    for (let i = 0; i < blocks.length; i++) {
      const block = blocks[i];
      const replacement = replacements[i];
      if (!block || !replacement) {
        continue;
      }
      splicePoints.push({ start: block.startIndex, end: block.endIndex, html: replacement.html });
      inlinedAttachmentIds.add(
        buildInlinedAttachmentKey(replacement.pageId, replacement.attachmentId),
      );
    }

    if (splicePoints.length === 0) {
      return { page, inlinedAttachmentIds: new Set() };
    }

    const newBody = this.applyReplacements(page.body, splicePoints);
    return {
      page: { ...page, body: newBody },
      inlinedAttachmentIds,
    };
  }

  private async buildImageReplacement(
    block: ParsedImageMacro,
    page: FetchedPage,
    pageImageAttachments: DiscoveredAttachment[],
  ): Promise<{ attachmentId: string; pageId: string; html: string } | null> {
    const resolved = await this.resolveAttachmentMetadata(
      block.resource,
      page,
      pageImageAttachments,
    );
    if (!resolved) {
      return null;
    }

    if (!isImageMediaType(resolved.mediaType)) {
      this.logger.debug({
        pageId: page.id,
        filename: resolved.filename,
        mediaType: resolved.mediaType,
        msg: 'Referenced attachment is not an image, leaving macro untouched',
      });
      return null;
    }

    // Cross-page lookups bypass discovery's allowedMimeTypes filter; re-check here.
    if (!this.isAllowedMediaType(resolved.mediaType)) {
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
    return { attachmentId: resolved.attachmentId, pageId: resolved.pageId, html };
  }

  private async resolveAttachmentMetadata(
    resource: ResourceRef,
    page: FetchedPage,
    pageImageAttachments: DiscoveredAttachment[],
  ): Promise<ResolvedAttachment | null> {
    if (resource.kind === 'external-url' || resource.kind === 'unknown') {
      return null;
    }

    if (resource.kind === 'current-attachment') {
      const match = pageImageAttachments.find((a) => a.title === resource.filename);
      if (!match) {
        this.logger.debug({
          pageId: page.id,
          filename: resource.filename,
          msg: 'Image filename not found among page attachments',
        });
        return null;
      }
      return {
        attachmentId: match.id,
        pageId: match.pageId,
        downloadPath: match.downloadPath,
        mediaType: match.mediaType,
        fileSize: match.fileSize,
        filename: match.title,
      };
    }

    const lookup = await this.lookupCrossPageAttachments(resource.spaceKey, resource.contentTitle);
    if (!lookup) {
      this.logger.debug({
        spaceKey: resource.spaceKey,
        contentTitle: resource.contentTitle,
        msg: 'Cross-page lookup returned no page',
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
        msg: 'Cross-page image filename not found',
      });
      return null;
    }
    return {
      attachmentId: match.id,
      pageId: lookup.pageId,
      downloadPath: match._links.download,
      mediaType: match.extensions.mediaType,
      fileSize: match.extensions.fileSize,
      filename: match.title,
    };
  }

  private async lookupCrossPageAttachments(
    spaceKey: string,
    contentTitle: string,
  ): Promise<PageAttachmentLookupResult | null> {
    // JSON.stringify avoids separator collisions that a plain concatenation would create.
    const cacheKey = JSON.stringify([spaceKey, contentTitle]);
    const cached = this.crossPageCache.get(cacheKey);
    if (cached) {
      return cached;
    }
    const promise = this.confluenceApiClient
      .fetchPageAttachmentsByTitle(spaceKey, contentTitle)
      .catch((err) => {
        // Don't cache errors permanently; a legitimate null (404) stays cached.
        this.crossPageCache.delete(cacheKey);
        this.logger.warn({
          spaceKey,
          contentTitle,
          err,
          msg: 'Cross-page attachment lookup failed',
        });
        return null;
      });
    this.crossPageCache.set(cacheKey, promise);
    return promise;
  }

  private isAllowedMediaType(mediaType: string): boolean {
    const normalized = mediaType.split(';')[0]?.trim().toLowerCase() ?? '';
    return this.config.ingestion.attachments.allowedMimeTypes.includes(normalized);
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
    mediaType: string,
    buffer: Buffer,
    filename: string,
  ): string {
    const base64 = buffer.toString('base64');
    const normalizedMediaType = mediaType.split(';')[0]?.trim().toLowerCase() ?? mediaType;
    const altValue = imgAttrs['ac:alt'] ?? filename;

    const parts: string[] = [`src="data:${normalizedMediaType};base64,${base64}"`];
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
