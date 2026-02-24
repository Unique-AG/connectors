import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import type { FetchFn } from '@qfetch/qfetch';
import { Span, TraceService } from 'nestjs-otel';
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

@Injectable()
export class UniqueContentService {
  private readonly logger = new Logger(UniqueContentService.name);

  public constructor(
    @Inject(UNIQUE_FETCH) private readonly fetch: FetchFn,
    private readonly trace: TraceService,
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

  @Span()
  public async uploadToStorage(
    writeUrl: string,
    content: ReadableStream<Uint8Array<ArrayBuffer>>,
    mime: string,
  ): Promise<void> {
    const span = this.trace.getSpan();

    const urlObj = new URL(writeUrl);
    const storageEndpoint = urlObj.origin;
    span?.setAttribute('storage_endpoint', storageEndpoint);

    this.logger.debug({ storageEndpoint }, 'Beginning content upload to Unique storage system');

    const response = await fetch(writeUrl, {
      method: 'PUT',
      headers: {
        'Content-Type': mime,
        'x-ms-blob-type': 'BlockBlob',
      },
      body: content,
      // @ts-expect-error: nodejs fetch requires `half` for streaming uploads
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
    options?: { skip?: number; take?: number },
  ): Promise<{ contents: ContentInfoItem[]; total: number }> {
    const request: PublicContentInfosRequest = {
      skip: options?.skip ?? 0,
      take: options?.take ?? 50,
      metadataFilter: filter,
    };

    const result = await this.getContentInfos(request);
    return {
      contents: result.contents,
      total: result.total ?? result.contents.length,
    };
  }

  @Span()
  public async search(
    request: PublicSearchRequest,
    scopeContext?: { userId: string; companyId: string },
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

  @Span()
  public async searchByScope(
    searchString: string,
    scopeIds: string[],
    scopeContext?: { userId: string; companyId: string },
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
    scopeContext?: { userId: string; companyId: string },
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
