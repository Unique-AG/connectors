import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '../../constants/ingestion.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { IngestionHttpClient } from '../clients/ingestion-http.client';
import { INGESTION_CLIENT, UniqueGraphqlClient } from '../clients/unique-graphql.client';
import { getScopeIdForIngestion } from '../ingestion.util';
import {
  CONTENT_UPSERT_MUTATION,
  ContentUpsertMutationInput,
  ContentUpsertMutationResult,
} from './unique-file-ingestion.consts';
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
    @Inject(INGESTION_CLIENT) private readonly ingestionClient: UniqueGraphqlClient,
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

  public async performFileDiff(
    fileList: FileDiffItem[],
    partialKey: string,
  ): Promise<FileDiffResponse> {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    const sharepointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
    const fileDiffUrl = new URL(uniqueConfig.fileDiffUrl);
    const fileDiffPath = fileDiffUrl.pathname + fileDiffUrl.search;

    const basePath = uniqueConfig.rootScopeName || sharepointBaseUrl;
    const scopeForRequest = getScopeIdForIngestion(
      uniqueConfig.ingestionMode,
      uniqueConfig.scopeId,
    );

    const diffRequest: FileDiffRequest = {
      basePath,
      partialKey,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      fileList,
      scope: scopeForRequest,
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
