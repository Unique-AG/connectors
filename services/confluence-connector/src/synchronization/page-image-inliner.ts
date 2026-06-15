import assert from 'node:assert';
import { Logger } from '@nestjs/common';
import { chunk, filter, indexBy, isNonNullish } from 'remeda';
import type { TenantConfig } from '../config';
import { BYTES_PER_MB } from '../config/ingestion.schema';
import type { ConfluenceApiClient, ConfluenceAttachment } from '../confluence-api';
import {
  findAllImageMacros,
  type ParsedImageMacro,
  type ResourceRef,
} from './confluence-tags-parser';
import { isImageMimeType, normalizeMimeType } from './mime-type';
import type { DiscoveredAttachment, FetchedPage } from './sync.types';

const IMAGE_INLINE_BATCH_SIZE = 20;

// ac:image attributes forwarded onto <img>; presentational hints (align, thumbnail, etc.) are dropped.
const AC_IMAGE_ATTRS_TO_KEEP: ReadonlyArray<[string, string]> = [
  ['ac:title', 'title'],
  ['ac:width', 'width'],
  ['ac:height', 'height'],
];

interface ResolvedAttachment {
  attachmentId: string;
  pageId: string;
  downloadPath: string;
  mediaType: string;
  fileSize: number;
  filename: string;
}

// An <ac:image> macro resolved to a base64-encoded <img>, plus the body span [start, end) it patches.
interface EncodedImagePatch {
  start: number;
  end: number;
  html: string;
}

export class PageImageInliner {
  private readonly logger = new Logger(PageImageInliner.name);

  public constructor(
    private readonly config: TenantConfig,
    private readonly confluenceApiClient: ConfluenceApiClient,
  ) {}

  public async inlineImagesInPage(
    page: FetchedPage,
    pageImageAttachments: DiscoveredAttachment[],
  ): Promise<FetchedPage> {
    if (!this.config.ingestion.attachments.inlineImagesEnabled || !page.body) {
      return page;
    }

    // Inlining must never lose a page: on any unexpected failure, fall back to the original body.
    try {
      const imageMacros = findAllImageMacros(page.body);
      if (imageMacros.length === 0) {
        return page;
      }

      const pageImageAttachmentsByTitle = indexBy(pageImageAttachments, (a) => a.title);

      const encodedImagePatches: EncodedImagePatch[] = [];
      // convert images to base64 in batches to cap concurrent downloads
      for (const imagesToProcessChunk of chunk(imageMacros, IMAGE_INLINE_BATCH_SIZE)) {
        const batchResults = await Promise.all(
          imagesToProcessChunk.map((macro) =>
            this.resolveBase64EncodedImagePatch(macro, page, pageImageAttachmentsByTitle),
          ),
        );
        encodedImagePatches.push(...filter(batchResults, isNonNullish));
      }

      if (encodedImagePatches.length === 0) {
        return page;
      }

      return { ...page, body: this.applyEncodedImagePatches(page.body, encodedImagePatches) };
    } catch (err) {
      this.logger.warn({
        pageId: page.id,
        err,
        msg: 'Image inlining failed, leaving page body unchanged',
      });
      return page;
    }
  }

  private async resolveBase64EncodedImagePatch(
    macro: ParsedImageMacro,
    page: FetchedPage,
    pageImageAttachmentsByTitle: Readonly<Record<string, DiscoveredAttachment>>,
  ): Promise<EncodedImagePatch | null> {
    try {
      const resolved = await this.resolveAttachmentMetadata(
        macro.resourceRef,
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
      const html = this.buildImgTag(macro.imgAttrs, resolved.mediaType, buffer, resolved.filename);

      return { start: macro.startIndex, end: macro.endIndex, html };
    } catch (err) {
      this.logger.warn({
        pageId: page.id,
        resource: macro.resourceRef,
        err,
        msg: 'Failed to inline image, leaving macro untouched',
      });
      return null;
    }
  }

  private async resolveAttachmentMetadata(
    resource: ResourceRef,
    pageImageAttachmentsByTitle: Readonly<Record<string, DiscoveredAttachment>>,
  ): Promise<ResolvedAttachment | null> {
    if (resource.kind === 'current-attachment') {
      return this.resolveCurrentPageAttachment(resource, pageImageAttachmentsByTitle);
    }

    if (resource.kind === 'other-page-attachment') {
      return this.resolveOtherPageAttachment(resource);
    }

    return null;
  }

  private resolveCurrentPageAttachment(
    resource: Extract<ResourceRef, { kind: 'current-attachment' }>,
    pageImageAttachmentsByTitle: Readonly<Record<string, DiscoveredAttachment>>,
  ): ResolvedAttachment | null {
    const match = pageImageAttachmentsByTitle[resource.filename];
    if (!match) {
      return null;
    }
    return this.fromDiscoveredAttachment(match);
  }

  private async resolveOtherPageAttachment(
    resource: Extract<ResourceRef, { kind: 'other-page-attachment' }>,
  ): Promise<ResolvedAttachment | null> {
    const lookup = await this.confluenceApiClient.fetchAttachmentsByPageTitle(
      resource.spaceKey,
      resource.contentTitle,
    );

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
    for await (const streamChunk of stream) {
      chunks.push(Buffer.isBuffer(streamChunk) ? streamChunk : Buffer.from(streamChunk));
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
      parts.push(`alt="${this.escapeAttr(altValue)}"`);
    }

    for (const [acAttr, htmlAttr] of AC_IMAGE_ATTRS_TO_KEEP) {
      const value = imgAttrs[acAttr];

      if (value === undefined) {
        continue;
      }

      parts.push(`${htmlAttr}="${this.escapeAttr(value)}"`);
    }
    return `<img ${parts.join(' ')} />`;
  }

  private applyEncodedImagePatches(original: string, patches: EncodedImagePatch[]): string {
    const sorted = [...patches].sort((a, b) => a.start - b.start);
    let result = '';
    let cursor = 0;

    for (const patch of sorted) {
      assert.ok(patch.start >= cursor, 'encoded image patches must not overlap');
      result += original.slice(cursor, patch.start) + patch.html;
      cursor = patch.end;
    }

    result += original.slice(cursor);
    return result;
  }

  private escapeAttr(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }
}
