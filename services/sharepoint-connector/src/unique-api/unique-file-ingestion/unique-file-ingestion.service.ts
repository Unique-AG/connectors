import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '../../constants/ingestion.constants';
import { StoreInternallyMode } from '../../constants/store-internally-mode.enum';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { IngestionHttpClient } from '../clients/ingestion-http.client';
import { INGESTION_CLIENT, UniqueGraphqlClient } from '../clients/unique-graphql.client';
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
    const uniqueConfig = this.configService.get('unique', { infer: true });
    const registrationInput: ContentUpsertMutationInput['input'] = {
      key: request.key,
      title: request.title,
      mimeType: request.mimeType,
      ownerType: UniqueOwnerType.Scope,
      url: request.url,
      byteSize: request.byteSize,
      ingestionConfig: {
        uniqueIngestionMode: 'SKIP_INGESTION',
      },
      ...(request.metadata ? { metadata: request.metadata } : {}),
    };

    const variables: ContentUpsertMutationInput = {
      input: registrationInput,
      scopeId: request.scopeId,
      sourceOwnerType: request.sourceOwnerType,
      sourceKind: request.sourceKind,
      sourceName: request.sourceName,
      storeInternally: uniqueConfig.storeInternally === StoreInternallyMode.Enabled,
      baseUrl: request.baseUrl,
    };

    if (request.fileAccess) {
      variables.input.fileAccess = request.fileAccess;
    }

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
    const uniqueConfig = this.configService.get('unique', { infer: true });
    const finalizationInput: ContentUpsertMutationInput['input'] = {
      key: request.key,
      title: request.title,
      mimeType: request.mimeType,
      ownerType: UniqueOwnerType.Scope,
      byteSize: request.byteSize,
      url: request.url,
      ingestionConfig: {
        uniqueIngestionMode: 'SKIP_INGESTION',
      },
      ...(request.metadata ? { metadata: request.metadata } : {}),
    };

    const variables: ContentUpsertMutationInput = {
      input: finalizationInput,
      scopeId: request.scopeId,
      sourceOwnerType: request.sourceOwnerType,
      sourceName: request.sourceName,
      sourceKind: request.sourceKind,
      fileUrl: request.fileUrl,
      storeInternally: uniqueConfig.storeInternally === StoreInternallyMode.Enabled,
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
    const fileDiffUrl = new URL(uniqueConfig.fileDiffUrl);
    const fileDiffPath = fileDiffUrl.pathname + fileDiffUrl.search;

    const diffRequest: FileDiffRequest = {
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
