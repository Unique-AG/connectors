import assert from 'node:assert';
import type { IngestionHttpClient } from '../clients/ingestion-http.client';
import type { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import type { UniqueApiClientAuthConfig, UniqueApiIngestion } from '../types';
import {
  CONTENT_UPSERT_MUTATION,
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
  UploadContentRequest,
} from './ingestion.types';

interface FileIngestionServiceDeps {
  ingestionClient: UniqueGraphqlClient;
  ingestionHttpClient: IngestionHttpClient;
  ingestionBaseUrl: string;
  uniqueConfig: {
    ingestionApiUrl: string;
    authMode: UniqueApiClientAuthConfig['mode'];
  };
}

export class FileIngestionService implements UniqueApiIngestion {
  private readonly ingestionClient: UniqueGraphqlClient;
  private readonly ingestionHttpClient: IngestionHttpClient;
  private readonly ingestionBaseUrl: string;
  private readonly uniqueConfig: { ingestionApiUrl: string; authMode: string };

  public constructor(deps: FileIngestionServiceDeps) {
    this.uniqueConfig = deps.uniqueConfig;
    this.ingestionClient = deps.ingestionClient;
    this.ingestionHttpClient = deps.ingestionHttpClient;
    this.ingestionBaseUrl = deps.ingestionBaseUrl;
  }

  public async upsertContent(request: ContentRegistrationRequest): Promise<IngestionApiResponse> {
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

  public async streamUpload(request: UploadContentRequest): Promise<void> {
    await this.ingestionClient.request(this.correctWriteUrl(request.uploadUrl), {
      method: 'PUT',
      headers: {
        'Content-Type': request.mimeType,
        'x-ms-blob-type': 'BlockBlob',
      },
      body: request.content,
      duplex: 'half',
    });
  }

  private correctWriteUrl(writeUrl: string): string {
    if (this.uniqueConfig.authMode === 'external') {
      return writeUrl;
    }
    const url = new URL(writeUrl);
    const key = url.searchParams.get('key');
    assert.ok(key, 'writeUrl is missing key parameter');
    return `${this.uniqueConfig.ingestionApiUrl}/scoped/upload?key=${encodeURIComponent(key)}`;
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
    // The ingestionBaseUrl can already have part of the path when running in external mode
    const pathPrefix = ingestionUrl.pathname === '/' ? '' : ingestionUrl.pathname;
    const fileDiffPath = `${pathPrefix}/v2/content/file-diff`;

    const diffRequest: FileDiffRequest = {
      partialKey,
      sourceKind,
      sourceName,
      fileList,
    };

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
