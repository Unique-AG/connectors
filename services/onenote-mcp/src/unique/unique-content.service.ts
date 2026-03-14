import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { FetchFn } from '@qfetch/qfetch';
import { Span, TraceService } from 'nestjs-otel';
import type { UniqueConfigNamespaced } from '~/config';
import { normalizeError } from '~/utils/normalize-error';
import { UNIQUE_FETCH, UNIQUE_REQUEST_HEADERS } from './unique.consts';
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

@Injectable()
export class UniqueContentService {
  private readonly logger = new Logger(UniqueContentService.name);
  private readonly apiBaseUrl: string;
  private readonly configuredHeaders: Record<string, string>;

  public constructor(
    @Inject(UNIQUE_FETCH) private readonly fetch: FetchFn,
    @Inject(UNIQUE_REQUEST_HEADERS) configuredHeaders: Record<string, string>,
    private readonly trace: TraceService,
    config: ConfigService<UniqueConfigNamespaced, true>,
  ) {
    this.apiBaseUrl = config.get('unique.apiBaseUrl', { infer: true });
    this.configuredHeaders = configuredHeaders;
  }

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

    try {
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
    } catch (error) {
      const normalized = normalizeError(error);
      this.logger.error(
        {
          endpoint: `${this.apiBaseUrl}/content/upsert`,
          method: 'POST',
          scopeId: content.scopeId,
          contentKey: content.input.key,
          mimeType: content.input.mimeType,
          hasFileUrl: !!content.fileUrl,
          configuredHeaders: this.configuredHeaders,
          errorMessage: normalized.message,
          errorName: normalized.name,
          errorStack: normalized.stack,
        },
        'Failed to upsert content in Unique API',
      );
      throw error;
    }
  }

  @Span()
  public async uploadToStorage(
    writeUrl: string,
    content: ReadableStream<Uint8Array<ArrayBuffer>>,
    mime: string,
    contentLength: number,
  ): Promise<void> {
    const span = this.trace.getSpan();

    const urlObj = new URL(writeUrl);
    const storageEndpoint = urlObj.origin;
    span?.setAttribute('storage_endpoint', storageEndpoint);

    const requestHeaders: Record<string, string> = {
      'Content-Type': mime,
      'Content-Length': String(contentLength),
      'x-ms-blob-type': 'BlockBlob',
    };

    this.logger.debug(
      { storageEndpoint, writeUrl, method: 'PUT', headers: requestHeaders },
      'Beginning content upload to Unique storage system',
    );

    const response = await fetch(writeUrl, {
      method: 'PUT',
      headers: requestHeaders,
      body: content,
      // @ts-expect-error: nodejs fetch requires `half` for streaming uploads
      duplex: 'half',
    });

    if (!response.ok) {
      let responseBody: string | undefined;
      try {
        responseBody = await response.text();
      } catch {
        responseBody = '<unable to read response body>';
      }

      span?.setAttribute('error', true);
      span?.setAttribute('http_status', response.status);
      this.logger.error(
        {
          status: response.status,
          statusText: response.statusText,
          storageEndpoint,
          writeUrl,
          requestHeaders,
          responseBody,
        },
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

    try {
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
    } catch (error) {
      const normalized = normalizeError(error);
      this.logger.error(
        {
          endpoint: `${this.apiBaseUrl}/content/infos`,
          method: 'POST',
          skip: request.skip,
          take: request.take,
          hasFilter: !!request.metadataFilter,
          configuredHeaders: this.configuredHeaders,
          errorMessage: normalized.message,
          errorName: normalized.name,
          errorStack: normalized.stack,
        },
        'Failed to retrieve content infos from Unique API',
      );
      throw error;
    }
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

  /**
   * @param scopeContext - When provided, overrides `x-user-id` and `x-company-id` headers
   *   to scope the search to the given user's permissions. When `undefined`, the search
   *   runs unscoped with service-level credentials — this is intentional for admin/ingestion flows.
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

    const requestHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(scopeContext && {
        'x-user-id': scopeContext.userId,
        'x-company-id': scopeContext.companyId,
      }),
    };

    const { searchString: _, ...redactedPayload } = payload as Record<string, unknown>;

    this.logger.log(
      {
        url: `${this.apiBaseUrl}search/search`,
        method: 'POST',
        configuredHeaders: this.configuredHeaders,
        requestHeaders,
        requestBody: redactedPayload,
      },
      'Search request details',
    );

    try {
      const response = await this.fetch('search/search', {
        method: 'POST',
        headers: requestHeaders,
        body: JSON.stringify(payload),
      });
      const result = PublicSearchResultSchema.parse(await response.json());

      span?.setAttribute('result_count', result.data.length);

      this.logger.log(
        { resultCount: result.data.length },
        'Search response received',
      );

      return result;
    } catch (error) {
      const normalized = normalizeError(error);
      this.logger.error(
        {
          endpoint: `${this.apiBaseUrl}/search/search`,
          method: 'POST',
          searchType: request.searchType,
          scopeCount: request.scopeIds?.length ?? 0,
          limit: request.limit,
          hasScopeContext: !!scopeContext,
          configuredHeaders: this.configuredHeaders,
          errorMessage: normalized.message,
          errorName: normalized.name,
          errorStack: normalized.stack,
        },
        'Failed to execute search in Unique API',
      );
      throw error;
    }
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
