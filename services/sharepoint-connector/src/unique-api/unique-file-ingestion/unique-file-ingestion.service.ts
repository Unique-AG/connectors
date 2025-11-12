import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '../../constants/ingestion.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { IngestionClient } from '../clients/ingestion.client';
import { IngestionHttpClient } from '../clients/ingestion-http.client';
import {
  CONTENT_DELETE_BY_KEY_MUTATION,
  CONTENT_UPSERT_MUTATION,
  ContentQueryInput,
  ContentUpsertMutationInput,
  ContentUpsertMutationResult,
  PAGINATED_CONTENT_QUERY,
} from './unique-file-ingestion.consts';
import type {
  ContentDeleteByKeyInput,
  ContentDeleteByKeyResult,
  ContentNode,
  PaginatedContentQueryResult,
} from './unique-file-ingestion.types';
import {
  ContentRegistrationRequest,
  FileDiffItem,
  FileDiffRequest,
  FileDiffResponse,
  IngestionApiResponse,
  IngestionFinalizationRequest,
} from './unique-file-ingestion.types';

@Injectable()
export class UniqueFileIngestionService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly ingestionClient: IngestionClient,
    private readonly ingestionHttpClient: IngestionHttpClient,
    private readonly configService: ConfigService<Config, true>,
  ) {}

  public async registerContent(request: ContentRegistrationRequest): Promise<IngestionApiResponse> {
    const variables: ContentUpsertMutationInput = {
      input: {
        key: request.key,
        title: request.title,
        mimeType: request.mimeType,
        ownerType: UniqueOwnerType.Scope,
        url: request.url,
      },
      scopeId: request.scopeId,
      sourceOwnerType: request.sourceOwnerType,
      sourceKind: request.sourceKind,
      sourceName: request.sourceName,
      storeInternally: false,
      baseUrl: request.baseUrl,
    };

    const result = await this.ingestionClient.get(
      async (client) =>
        await client.request<ContentUpsertMutationResult, ContentUpsertMutationInput>(
          CONTENT_UPSERT_MUTATION,
          variables,
        ),
    );

    assert.ok(result?.contentUpsert, 'Invalid response from Unique API content registration');
    return result.contentUpsert;
  }

  public async finalizeIngestion(request: IngestionFinalizationRequest): Promise<{ id: string }> {
    const variables: ContentUpsertMutationInput = {
      input: {
        key: request.key,
        title: request.title,
        mimeType: request.mimeType,
        ownerType: UniqueOwnerType.Scope,
        byteSize: request.byteSize,
        url: request.url,
      },
      scopeId: request.scopeId,
      sourceOwnerType: request.sourceOwnerType,
      sourceName: request.sourceName,
      sourceKind: request.sourceKind,
      fileUrl: request.fileUrl,
      storeInternally: false,
      baseUrl: request.baseUrl,
    };

    const result = await this.ingestionClient.get(
      async (client) =>
        await client.request<ContentUpsertMutationResult, ContentUpsertMutationInput>(
          CONTENT_UPSERT_MUTATION,
          variables,
        ),
    );

    assert.ok(result?.contentUpsert?.id, 'Invalid response from Unique API ingestion finalization');
    return { id: result.contentUpsert.id };
  }

  /**
   * Queries existing content by scope ID and specific keys for deletion
   */
  public async queryContentByScopeAndKeys(scopeId: string, keys: string[]): Promise<ContentNode[]> {
    if (keys.length === 0) {
      return [];
    }

    const variables: ContentQueryInput = {
      where: {
        ownerId: { equals: scopeId },
        key: { in: keys },
      },
      take: keys.length, // Only expect as many results as keys we requested
    };

    const result = await this.ingestionClient.get(
      async (client) =>
        await client.request<PaginatedContentQueryResult, ContentQueryInput>(
          PAGINATED_CONTENT_QUERY,
          variables,
        ),
    );

    return result?.paginatedContent?.nodes || [];
  }

  /**
   * Deletes a content item by its key, ownerType, and scopeId
   */
  public async deleteContentByKey(
    key: string,
    ownerType: string,
    scopeId?: string,
    url?: string,
    baseUrl?: string,
  ): Promise<boolean> {
    const variables: ContentDeleteByKeyInput = {
      key,
      ownerType,
      scopeId,
      url,
      baseUrl,
    };

    const result = await this.ingestionClient.get(
      async (client) =>
        await client.request<ContentDeleteByKeyResult, ContentDeleteByKeyInput>(
          CONTENT_DELETE_BY_KEY_MUTATION,
          variables,
        ),
    );

    return result?.contentDeleteByKey || false;
  }

  public async performFileDiff(
    fileList: FileDiffItem[],
    partialKey: string,
  ): Promise<FileDiffResponse> {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    const sharepointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
    const fileDiffUrl = new URL(uniqueConfig.fileDiffUrl);
    const fileDiffPath = fileDiffUrl.pathname + fileDiffUrl.search;

    const basePath = uniqueConfig.rootScopeName || sharepointBaseUrl;

    const diffRequest: FileDiffRequest = {
      basePath,
      partialKey,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      fileList,
    };

    this.logger.debug(`File diff request payload: ${JSON.stringify(diffRequest, null, 2)}`);

    const { statusCode, body } = await this.ingestionHttpClient.request({
      method: 'POST',
      path: fileDiffPath,
      body: JSON.stringify(diffRequest),
    });

    if (statusCode < 200 || statusCode >= 300) {
      const errorText = await body.text().catch(() => 'No response body');
      throw new Error(`File diff request failed with status ${statusCode}. Response: ${errorText}`);
    }

    const responseData = await body.json();
    assert.ok(responseData, 'Invalid response from Unique API file diff');
    return responseData as FileDiffResponse;
  }
}
