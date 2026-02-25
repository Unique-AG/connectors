import assert from 'node:assert';
import { sanitizePath } from '@unique-ag/utils';
import type { IngestionHttpClient } from '../clients/ingestion-http.client';
import type { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import {
  CONTENT_UPDATE_METADATA_MUTATION,
  CONTENT_UPSERT_MUTATION,
  ContentUpdateMetadataMutationInput,
  ContentUpdateMetadataMutationResponse,
  ContentUpdateMetadataResponse,
  type ContentUpsertMutationInput,
  type ContentUpsertMutationResult,
} from './ingestion.queries';
import type {
  ContentRegistrationRequest,
  FileDiffItem,
  FileDiffRequest,
  FileDiffResponse,
  IngestionApiResponse,
  IngestionFinalizationRequest,
} from './ingestion.types';
import { UniqueIngestionFacade } from './unique-ingestion.facade';

export class FileIngestionService implements UniqueIngestionFacade {
  public constructor(
    private readonly ingestionClient: UniqueGraphqlClient,
    private readonly ingestionHttpClient: IngestionHttpClient,
    private readonly ingestionBaseUrl: string,
  ) {}

  public async updateMetadata(
    request: ContentUpdateMetadataMutationInput,
  ): Promise<ContentUpdateMetadataResponse> {
    const result = await this.ingestionClient.request<
      ContentUpdateMetadataMutationResponse,
      ContentUpdateMetadataMutationInput
    >(CONTENT_UPDATE_METADATA_MUTATION, request);

    assert.ok(result?.contentUpdateMetadata, 'Invalid response from Unique API metadata update');
    return result.contentUpdateMetadata;
  }

  public async registerContent(request: ContentRegistrationRequest): Promise<IngestionApiResponse> {
    const variables: ContentUpsertMutationInput = {
      input: {
        key: request.key,
        title: request.title,
        mimeType: request.mimeType,
        ownerType: request.ownerType,
        url: request.url,
        byteSize: request.byteSize,
        metadata: request.metadata,
      },
      scopeId: request.scopeId,
      sourceOwnerType: request.sourceOwnerType,
      sourceKind: request.sourceKind,
      sourceName: request.sourceName,
      storeInternally: request.storeInternally,
      baseUrl: request.baseUrl,
    };

    if (request.fileAccess) {
      variables.input.fileAccess = request.fileAccess;
    }

    const result = await this.ingestionClient.request<
      ContentUpsertMutationResult,
      ContentUpsertMutationInput
    >(CONTENT_UPSERT_MUTATION, variables);

    assert.ok(result?.contentUpsert, 'Invalid response from Unique API content registration');
    return result.contentUpsert;
  }

  public async finalizeIngestion(request: IngestionFinalizationRequest): Promise<{ id: string }> {
    const variables: ContentUpsertMutationInput = {
      input: {
        key: request.key,
        title: request.title,
        mimeType: request.mimeType,
        ownerType: request.ownerType,
        byteSize: request.byteSize,
        url: request.url,
        metadata: request.metadata,
      },
      scopeId: request.scopeId,
      sourceOwnerType: request.sourceOwnerType,
      sourceName: request.sourceName,
      sourceKind: request.sourceKind,
      fileUrl: request.fileUrl,
      storeInternally: request.storeInternally,
      baseUrl: request.baseUrl,
    };

    const result = await this.ingestionClient.request<
      ContentUpsertMutationResult,
      ContentUpsertMutationInput
    >(CONTENT_UPSERT_MUTATION, variables);

    assert.ok(result?.contentUpsert?.id, 'Invalid response from Unique API ingestion finalization');
    return { id: result.contentUpsert.id };
  }

  public async performFileDiff(
    fileList: FileDiffItem[],
    partialKey: string,
    sourceKind: string,
    sourceName: string,
  ): Promise<FileDiffResponse> {
    const ingestionUrl = new URL(this.ingestionBaseUrl);

    const diffRequest: FileDiffRequest = {
      partialKey,
      sourceKind,
      sourceName,
      fileList,
    };

    const { statusCode, body } = await this.ingestionHttpClient.request({
      method: 'POST',
      // The ingestionServiceBaseUrl can have already part of the path when running in external mode
      path: sanitizePath({
        path: `${ingestionUrl.pathname}/v2/content/file-diff`,
        prefixWithSlash: true,
      }),
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
