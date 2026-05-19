import assert from 'node:assert';
import { Logger } from '@nestjs/common';
import { Parser } from 'htmlparser2';
import pLimit from 'p-limit';
import type { TenantConfig } from '../config';
import { BYTES_PER_MB } from '../config/ingestion.schema';
import type {
  ConfluenceApiClient,
  ConfluenceAttachment,
  PageAttachmentLookupResult,
} from '../confluence-api';
import type { DiscoveredAttachment, FetchedPage } from './sync.types';

// ac:image attributes we forward onto the produced <img>. Other presentational hints
// (ac:align, ac:thumbnail, ac:vspace, ac:hspace, ac:border, ac:class, ac:style) are
// Confluence-renderer specific and dropped.
const AC_IMAGE_ATTRS_TO_KEEP: ReadonlyArray<[string, string]> = [
  ['ac:title', 'title'],
  ['ac:width', 'width'],
  ['ac:height', 'height'],
];

// Per-page cap on concurrent image downloads. Outer page concurrency is bounded by
// processing.concurrency; this guards against an image-heavy page allocating a
// per-image Buffer for every <ac:image> in one go.
const IMAGE_DOWNLOAD_CONCURRENCY = 5;

type ResourceRef =
  | { kind: 'current-attachment'; filename: string }
  | {
      kind: 'cross-page-attachment';
      filename: string;
      spaceKey: string;
      contentTitle: string;
    }
  | { kind: 'external-url' }
  | { kind: 'unknown' };

interface ParsedImageBlock {
  startIndex: number;
  endIndex: number;
  imgAttrs: Record<string, string>;
  resource: ResourceRef;
}

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

// inlinedAttachmentIds entries are keyed by ${pageId}::${attachmentId} to avoid
// collisions across pages on instances where attachment ids are not globally unique.
export function buildInlinedAttachmentKey(pageId: string, attachmentId: string): string {
  return `${pageId}::${attachmentId}`;
}

export class PageImageInliner {
  private readonly logger = new Logger(PageImageInliner.name);
  // Cross-page page-by-title lookups are cached for the duration of one sync run.
  // The orchestrator calls resetCrossPageCache() at the start of every sync so that
  // attachment changes on a target page (or a previously-missing page becoming
  // available) are picked up on the next cycle.
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

    const blocks = this.parseImageBlocks(page.body);
    if (blocks.length === 0) {
      return { page, inlinedAttachmentIds: new Set() };
    }

    const limit = pLimit(IMAGE_DOWNLOAD_CONCURRENCY);
    const resolutions = await Promise.all(
      blocks.map((block) =>
        limit(() => this.resolveAndDownload(block, page, pageImageAttachments)).catch((err) => {
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
    const replacements: Array<{ start: number; end: number; html: string }> = [];

    for (let i = 0; i < blocks.length; i++) {
      const block = blocks[i];
      const resolution = resolutions[i];
      if (!block || !resolution) {
        continue;
      }
      replacements.push({ start: block.startIndex, end: block.endIndex, html: resolution.html });
      inlinedAttachmentIds.add(
        buildInlinedAttachmentKey(resolution.pageId, resolution.attachmentId),
      );
    }

    if (replacements.length === 0) {
      return { page, inlinedAttachmentIds: new Set() };
    }

    const newBody = this.splice(page.body, replacements);
    return {
      page: { ...page, body: newBody },
      inlinedAttachmentIds,
    };
  }

  private async resolveAndDownload(
    block: ParsedImageBlock,
    page: FetchedPage,
    pageImageAttachments: DiscoveredAttachment[],
  ): Promise<{ attachmentId: string; pageId: string; html: string } | null> {
    const resolved = await this.resolveAttachment(block.resource, page, pageImageAttachments);
    if (!resolved) {
      return null;
    }

    if (!this.isImageMediaType(resolved.mediaType)) {
      this.logger.debug({
        pageId: page.id,
        filename: resolved.filename,
        mediaType: resolved.mediaType,
        msg: 'Referenced attachment is not an image, leaving macro untouched',
      });
      return null;
    }

    // Current-page attachments have already been filtered by allowedMimeTypes during
    // discovery, but cross-page lookups read raw attachment metadata from the API and
    // must be re-checked here so unsupported image formats (GIF, WebP, SVG, etc.) are
    // never inlined.
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

  private async resolveAttachment(
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

    const lookup = await this.lookupCrossPage(resource.spaceKey, resource.contentTitle);
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

  private async lookupCrossPage(
    spaceKey: string,
    contentTitle: string,
  ): Promise<PageAttachmentLookupResult | null> {
    // JSON.stringify avoids collisions when either component contains a separator
    // character that a plain concatenation would merge into a single ambiguous key.
    const cacheKey = JSON.stringify([spaceKey, contentTitle]);
    const cached = this.crossPageCache.get(cacheKey);
    if (cached) {
      return cached;
    }
    const promise = this.confluenceApiClient
      .fetchPageAttachmentsByTitle(spaceKey, contentTitle)
      .catch((err) => {
        // Don't permanently cache transient errors; allow retry on the next reference.
        // A legitimate 404 resolves to null and stays cached for the rest of the sync.
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

  private isImageMediaType(mediaType: string): boolean {
    const normalized = mediaType.split(';')[0]?.trim().toLowerCase() ?? '';
    return normalized.startsWith('image/');
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

  private splice(
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

  private parseImageBlocks(body: string): ParsedImageBlock[] {
    const blocks: ParsedImageBlock[] = [];

    let imageOpen: { startIndex: number; imgAttrs: Record<string, string> } | null = null;
    let attachmentOpen: {
      filename: string;
      page: { spaceKey: string; contentTitle: string } | null;
    } | null = null;
    let externalUrl = false;

    const parser: Parser = new Parser(
      {
        onopentag: (name, attrs) => {
          if (name === 'ac:image') {
            imageOpen = { startIndex: parser.startIndex, imgAttrs: { ...attrs } };
            attachmentOpen = null;
            externalUrl = false;
            return;
          }
          if (!imageOpen) {
            return;
          }
          if (name === 'ri:attachment') {
            const filename = attrs['ri:filename'];
            if (filename) {
              attachmentOpen = { filename, page: null };
            }
            return;
          }
          if (name === 'ri:page' && attachmentOpen) {
            const spaceKey = attrs['ri:space-key'];
            const contentTitle = attrs['ri:content-title'];
            if (spaceKey && contentTitle) {
              attachmentOpen.page = { spaceKey, contentTitle };
            }
            return;
          }
          if (name === 'ri:url') {
            externalUrl = true;
          }
        },
        onclosetag: (name) => {
          if (name !== 'ac:image' || !imageOpen) {
            return;
          }
          // parser.endIndex points at the final '>' of </ac:image>, so +1 is exclusive.
          const endIndex = parser.endIndex + 1;
          // htmlparser2 synthesizes onclosetag for every still-open tag when parser.end()
          // runs at EOF. Reject blocks whose slice does not terminate with a real close
          // ('</ac:image>' or self-closing '/>') so we never splice into unrelated content.
          const blockText = body.slice(imageOpen.startIndex, endIndex);
          if (!blockText.endsWith('</ac:image>') && !blockText.endsWith('/>')) {
            imageOpen = null;
            attachmentOpen = null;
            externalUrl = false;
            return;
          }
          const resource = resolveResource(attachmentOpen, externalUrl);
          blocks.push({
            startIndex: imageOpen.startIndex,
            endIndex,
            imgAttrs: imageOpen.imgAttrs,
            resource,
          });
          imageOpen = null;
          attachmentOpen = null;
          externalUrl = false;
        },
      },
      { xmlMode: true },
    );
    parser.write(body);
    parser.end();
    return blocks;
  }
}

function resolveResource(
  attachmentOpen: {
    filename: string;
    page: { spaceKey: string; contentTitle: string } | null;
  } | null,
  externalUrl: boolean,
): ResourceRef {
  if (externalUrl) {
    return { kind: 'external-url' };
  }
  if (!attachmentOpen) {
    return { kind: 'unknown' };
  }
  if (attachmentOpen.page) {
    return {
      kind: 'cross-page-attachment',
      filename: attachmentOpen.filename,
      spaceKey: attachmentOpen.page.spaceKey,
      contentTitle: attachmentOpen.page.contentTitle,
    };
  }
  return { kind: 'current-attachment', filename: attachmentOpen.filename };
}

function escapeAttr(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}
