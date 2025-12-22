import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { TenantConfigLoaderService } from '../../config/tenant-config-loader.service';
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
  public constructor(
    @Inject(INGESTION_CLIENT) private readonly ingestionClient: UniqueGraphqlClient,
    private readonly ingestionHttpClient: IngestionHttpClient,
    private readonly configService: ConfigService<Config, true>,
    private readonly tenantConfigLoaderService: TenantConfigLoaderService,
  ) {}

  public async registerContent(request: ContentRegistrationRequest): Promise<IngestionApiResponse> {
    const tenantConfig = this.tenantConfigLoaderService.loadTenantConfig();
    const variables: ContentUpsertMutationInput = {
      input: {
        key: request.key,
        title: request.title,
        mimeType: request.mimeType,
        ownerType: UniqueOwnerType.Scope,
        url: request.url,
        byteSize: request.byteSize,
        metadata: request.metadata,
      },
      scopeId: request.scopeId,
      sourceOwnerType: request.sourceOwnerType,
      sourceKind: request.sourceKind,
      sourceName: request.sourceName,
      storeInternally: false, // Removed global default - use site-level config
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
    const tenantConfig = this.tenantConfigLoaderService.loadTenantConfig();
    const variables: ContentUpsertMutationInput = {
      input: {
        key: request.key,
        title: request.title,
        mimeType: request.mimeType,
        ownerType: UniqueOwnerType.Scope,
        byteSize: request.byteSize,
        url: request.url,
        metadata: request.metadata,
      },
      scopeId: request.scopeId,
      sourceOwnerType: request.sourceOwnerType,
      sourceName: request.sourceName,
      sourceKind: request.sourceKind,
      fileUrl: request.fileUrl,
      storeInternally: false, // Removed global default - use site-level config
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
  ): Promise<FileDiffResponse> {
    const tenantConfig = this.tenantConfigLoaderService.loadTenantConfig();
    const ingestionUrl = new URL(tenantConfig.ingestionServiceBaseUrl);
    // The ingestionServiceBaseUrl can have already part of the path when running in external mode
    const pathPrefix = ingestionUrl.pathname === '/' ? '' : ingestionUrl.pathname;
    const fileDiffPath = `${pathPrefix}/v2/content/file-diff`;

    const diffRequest: FileDiffRequest = {
      partialKey,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
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
