import assert from 'node:assert';
import { randomUUID } from 'node:crypto';
import { createReadStream, createWriteStream } from 'node:fs';
import { rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { FetchFn } from '@qfetch/qfetch';
import { Span, TraceService } from 'nestjs-otel';
import type { UniqueConfigNamespaced } from '~/config';
import { UNIQUE_FETCH } from './unique.consts';
import {
  type ContentInfoItem,
  type MetadataFilter,
  type PublicContentInfosRequest,
  PublicContentInfosRequestSchema,
  type PublicContentInfosResult,
  PublicContentInfosResultSchema,
  type PublicContentUpsertRequest,
  PublicContentUpsertRequestSchema,
  type PublicContentUpsertResult,
  PublicContentUpsertResultSchema,
  type PublicSearchRequest,
  PublicSearchRequestSchema,
  type PublicSearchResult,
  PublicSearchResultSchema,
  type SearchResultItem,
  SearchType,
} from './unique.dtos';
import type { UniqueIdentity } from './unique-identity.types';

/**
 * A download streamed to a local temp file, ready to upload with an authoritative `Content-Length`.
 * Produced by {@link UniqueContentService.spoolContent}; the caller owns the file and must call
 * {@link cleanup} once the upload has finished (or failed).
 */
export interface SpooledContent {
  /** Absolute path of the temp file the content was streamed to. */
  path: string;
  /** Authoritative byte size from `fstat`, used as the upload `Content-Length`. */
  size: number;
  /** Removes the temp file. Safe to call more than once (`force` no-ops if already gone). */
  cleanup: () => Promise<void>;
}

@Injectable()
export class UniqueContentService {
  private readonly logger = new Logger(UniqueContentService.name);

  public constructor(
    @Inject(UNIQUE_FETCH) private readonly fetch: FetchFn,
    private readonly trace: TraceService,
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
  ) {}

  @Span()
  public async upsertContent(
    content: PublicContentUpsertRequest,
  ): Promise<PublicContentUpsertResult> {
    const span = this.trace.getSpan();
    span?.setAttribute('scope_id', content.scopeId ?? '');
    span?.setAttribute('content_key', content.input.key);
    span?.setAttribute('mime_type', content.input.mimeType);
    span?.setAttribute('store_internally', content.storeInternally);
    span?.setAttribute('has_file_url', !!content.fileUrl);

    const payload = PublicContentUpsertRequestSchema.encode(content);

    this.logger.debug(
      {
        scopeId: content.scopeId,
        contentKey: content.input.key,
        mimeType: content.input.mimeType,
        storeInternally: content.storeInternally,
        hasFileUrl: !!content.fileUrl,
      },
      'Creating or updating content record in Unique system',
    );

    const response = await this.fetch('content/upsert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = PublicContentUpsertResultSchema.parse(await response.json());

    this.logger.log(
      {
        scopeId: content.scopeId,
        contentKey: content.input.key,
        mimeType: content.input.mimeType,
        hasWriteUrl: !!result.writeUrl,
        hasReadUrl: !!result.readUrl,
      },
      'Successfully created or updated content record in Unique system',
    );

    return result;
  }

  /**
   * Streams a content download to a temp file at constant memory and returns its path plus an
   * authoritative byte size (`fstat`). Call this *before* opening a Unique content record
   * ({@link upsertContent}) so a failed download (e.g. a 403 on a recording the caller can't read)
   * never leaves a dangling, empty record behind. The caller must {@link SpooledContent.cleanup}
   * the returned file once the upload has finished or failed.
   */
  @Span()
  public async spoolContent(
    content: () => Promise<ReadableStream<Uint8Array<ArrayBuffer>>>,
  ): Promise<SpooledContent> {
    const span = this.trace.getSpan();
    const tmpPath = join(tmpdir(), `teams-upload-${randomUUID()}`);

    try {
      // The MS Graph body is a web stream; Readable.fromWeb adapts it to a Node stream so the
      // pipeline can write it to disk with backpressure (constant memory).
      await pipeline(Readable.fromWeb(await content()), createWriteStream(tmpPath));
      const { size } = await stat(tmpPath);
      span?.setAttribute('content_length', size);
      return { path: tmpPath, size, cleanup: () => rm(tmpPath, { force: true }) };
    } catch (error) {
      // Remove any partial spool before propagating, so a download failure leaves nothing behind.
      await rm(tmpPath, { force: true });
      throw error;
    }
  }

  @Span()
  public async uploadToStorage(
    writeUrl: string,
    spooled: SpooledContent,
    mime: string,
  ): Promise<void> {
    const span = this.trace.getSpan();

    const uploadUrl = this.correctWriteUrl(writeUrl);
    const storageEndpoint = new URL(uploadUrl).origin;
    span?.setAttribute('storage_endpoint', storageEndpoint);
    span?.setAttribute('content_length', spooled.size);

    this.logger.debug({ storageEndpoint }, 'Beginning content upload to Unique storage system');

    // Azure Blob's single `PUT Blob` rejects `Transfer-Encoding: chunked` (400 UnsupportedHeader)
    // and requires a `Content-Length`. The spooled file gives us an authoritative size, and undici
    // sends a sized, non-chunked body when an explicit Content-Length is set.
    const response = await fetch(uploadUrl, {
      method: 'PUT',
      headers: {
        'Content-Type': mime,
        'Content-Length': String(spooled.size),
        'x-ms-blob-type': 'BlockBlob',
      },
      // Stream the spooled file back as the request body. `duplex: 'half'` is required for a
      // streaming request body.
      body: Readable.toWeb(createReadStream(spooled.path)),
      duplex: 'half',
    });

    if (!response.ok) {
      span?.setAttribute('error', true);
      span?.setAttribute('http_status', response.status);
      this.logger.error(
        { status: response.status, storageEndpoint },
        'Unique storage system rejected content upload with error',
      );
      assert.fail(`Unique storage upload failed: ${response.status}`);
    }

    span?.setAttribute('http_status', response.status);
    this.logger.debug({ storageEndpoint }, 'Successfully completed content upload to storage');
  }

  // HACK (mirrors outlook-semantic-mcp): in cluster_local mode the storeInternally
  // writeUrl points at the public, Kong-gateway-fronted storage endpoint, which
  // in-cluster pods cannot reach (egress is policy-denied → connect timeout). Rewrite
  // it to route through node-ingestion's scoped upload endpoint, reachable in-cluster.
  // In external mode the public writeUrl is used as-is.
  private correctWriteUrl(writeUrl: string): string {
    const config = this.config.get('unique', { infer: true });
    if (config.serviceAuthMode === 'external') {
      return writeUrl;
    }
    const key = new URL(writeUrl).searchParams.get('key');
    assert.ok(key, 'writeUrl is missing key parameter');
    const target = new URL('/scoped/upload', config.ingestionServiceBaseUrl);
    target.searchParams.set('key', key);
    return target.toString();
  }

  // One skip/take page; callers paginate explicitly.
  @Span()
  public async getContentInfos(
    request: PublicContentInfosRequest,
  ): Promise<PublicContentInfosResult> {
    const span = this.trace.getSpan();
    span?.setAttribute('skip', request.skip ?? 0);
    span?.setAttribute('take', request.take ?? 50);
    span?.setAttribute('has_filter', !!request.metadataFilter);

    const payload = PublicContentInfosRequestSchema.encode(request);

    this.logger.debug(
      { skip: request.skip, take: request.take, hasFilter: !!request.metadataFilter },
      'Querying content information from Unique system',
    );

    const response = await this.fetch('content/infos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = PublicContentInfosResultSchema.parse(await response.json());

    span?.setAttribute('result_count', result.contents.length);
    span?.setAttribute('total', result.total ?? result.contents.length);

    this.logger.debug(
      { resultCount: result.contents.length, total: result.total },
      'Successfully retrieved content information from Unique system',
    );

    return result;
  }

  @Span()
  public async findByMetadata(
    filter: MetadataFilter,
    options?: { skip?: number; take?: number; sourceKind?: string },
  ): Promise<{ contents: ContentInfoItem[]; total: number }> {
    const request: PublicContentInfosRequest = {
      skip: options?.skip ?? 0,
      take: options?.take ?? 50,
      metadataFilter: filter,
      sourceKind: options?.sourceKind,
    };

    const result = await this.getContentInfos(request);
    return {
      contents: result.contents,
      total: result.total ?? result.contents.length,
    };
  }

  /**
   * @param scopeContext - When provided, overrides `x-user-id` and `x-company-id` headers
   *   to scope the search to the given user's permissions. When `undefined`, the search
   *   runs unscoped with service-level credentials — this is intentional for admin/ingestion flows.
   *
   * One page/limit request; relevance-ranked, so callers don't collect all pages.
   */
  @Span()
  public async search(
    request: PublicSearchRequest,
    scopeContext?: UniqueIdentity,
  ): Promise<PublicSearchResult> {
    const span = this.trace.getSpan();
    span?.setAttribute('search_type', request.searchType);
    span?.setAttribute('has_scope_ids', !!request.scopeIds?.length);
    span?.setAttribute('has_content_ids', !!request.contentIds?.length);
    span?.setAttribute('has_metadata_filter', !!request.metaDataFilter);
    span?.setAttribute('limit', request.limit ?? 10);
    span?.setAttribute('page', request.page ?? 0);

    const payload = PublicSearchRequestSchema.encode(request);

    this.logger.debug(
      {
        searchType: request.searchType,
        scopeCount: request.scopeIds?.length ?? 0,
        contentCount: request.contentIds?.length ?? 0,
        hasFilter: !!request.metaDataFilter,
        limit: request.limit,
        page: request.page,
      },
      'Executing content search in Unique system',
    );

    const response = await this.fetch('search/search', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(scopeContext && {
          'x-user-id': scopeContext.userId,
          'x-company-id': scopeContext.companyId,
        }),
      },
      body: JSON.stringify(payload),
    });
    const result = PublicSearchResultSchema.parse(await response.json());

    span?.setAttribute('result_count', result.data.length);

    this.logger.debug(
      { resultCount: result.data.length },
      'Successfully executed content search in Unique system',
    );

    return result;
  }

  /** Scoped search — requires a resolved Unique identity. Use this in user-facing tools. */
  @Span()
  public async scopedSearch(
    request: PublicSearchRequest,
    scopeContext: UniqueIdentity,
  ): Promise<PublicSearchResult> {
    return this.search(request, scopeContext);
  }

  @Span()
  public async searchByScope(
    searchString: string,
    scopeIds: string[],
    scopeContext?: UniqueIdentity,
    options?: {
      limit?: number;
      page?: number;
      scoreThreshold?: number;
    },
  ): Promise<SearchResultItem[]> {
    const request: PublicSearchRequest = {
      searchString,
      searchType: SearchType.VECTOR,
      scopeIds,
      limit: options?.limit ?? 10,
      page: options?.page ?? 0,
      scoreThreshold: options?.scoreThreshold,
    };

    const result = await this.search(request, scopeContext);
    return result.data;
  }

  @Span()
  public async searchByContent(
    searchString: string,
    contentIds: string[],
    scopeContext?: UniqueIdentity,
    options?: {
      limit?: number;
      page?: number;
      scoreThreshold?: number;
    },
  ): Promise<SearchResultItem[]> {
    const request: PublicSearchRequest = {
      searchString,
      searchType: SearchType.VECTOR,
      contentIds,
      limit: options?.limit ?? 10,
      page: options?.page ?? 0,
      scoreThreshold: options?.scoreThreshold,
    };

    const result = await this.search(request, scopeContext);
    return result.data;
  }
}
