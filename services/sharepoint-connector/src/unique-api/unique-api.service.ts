import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { GraphQLClient } from 'graphql-request';
import { Client } from 'undici';
import { Config } from '../config';
import {
  INGESTION_SOURCE_KIND,
  INGESTION_SOURCE_NAME,
  PATH_BASED_INGESTION,
} from '../constants/ingestion.constants';
import { UniqueOwnerType } from '../constants/unique-owner-type.enum';
import { UNIQUE_HTTP_CLIENT } from '../http-client.tokens';
import { normalizeError } from '../utils/normalize-error';
import {
  type ContentRegistrationRequest,
  type FileDiffItem,
  type FileDiffRequest,
  type FileDiffResponse,
  type IngestionApiResponse,
  type IngestionFinalizationRequest,
} from './unique-api.types';

@Injectable()
export class UniqueApiService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly limiter: Bottleneck;
  private readonly ingestionHttpExtraHeaders: Record<string, string>;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    @Inject(UNIQUE_HTTP_CLIENT) private readonly httpClient: Client,
  ) {
    const rateLimitPerMinute = this.configService.get('unique.apiRateLimitPerMinute', {
      infer: true,
    });
    this.ingestionHttpExtraHeaders =
      this.configService.get('unique.ingestionHttpExtraHeaders', { infer: true }) || {};

    this.limiter = new Bottleneck({
      reservoir: rateLimitPerMinute,
      reservoirRefreshAmount: rateLimitPerMinute,
      reservoirRefreshInterval: 60000,
    });
  }

  public async registerContent(
    request: ContentRegistrationRequest,
    uniqueToken: string,
  ): Promise<IngestionApiResponse> {
    const client = this.createGraphqlClient(uniqueToken);
    const variables = {
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

    const errorMessage = 'Content registration failed:';
    return await this.makeRateLimitedRequest(errorMessage, async () => {
      const result = await client.request<{ contentUpsert?: IngestionApiResponse }>(
        this.getContentUpsertMutation(),
        variables,
      );

      assert.ok(result?.contentUpsert, 'Invalid response from Unique API content registration');
      return result.contentUpsert;
    });
  }

  public async performFileDiff(
    fileList: FileDiffItem[],
    uniqueToken: string,
    partialKey: string,
  ): Promise<FileDiffResponse> {
    const scopeId = this.configService.get('unique.scopeId', { infer: true });
    const sharepointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
    const fileDiffUrl = this.configService.get('unique.fileDiffUrl', { infer: true });
    const url = new URL(fileDiffUrl);
    const path = url.pathname + url.search;

    const diffRequest: FileDiffRequest = {
      basePath: sharepointBaseUrl,
      partialKey,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      fileList,
      scope: scopeId ?? PATH_BASED_INGESTION,
    };

    this.logger.debug(`File diff request payload: ${JSON.stringify(diffRequest, null, 2)}`);

    const errorMessage = 'File diff failed:';
    return await this.makeRateLimitedRequest(errorMessage, async () => {
      const { statusCode, body } = await this.httpClient.request({
        method: 'POST',
        path,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${uniqueToken}`,
          ...this.ingestionHttpExtraHeaders,
        },
        body: JSON.stringify(diffRequest),
      });

      if (statusCode < 200 || statusCode >= 300) {
        const errorText = await body.text().catch(() => 'No response body');
        throw new Error(
          `File diff request failed with status ${statusCode}. Response: ${errorText}`,
        );
      }

      const responseData = await body.json();
      assert.ok(responseData, 'Invalid response from Unique API file diff');
      return responseData as FileDiffResponse;
    });
  }

  public async finalizeIngestion(
    request: IngestionFinalizationRequest,
    uniqueToken: string,
  ): Promise<{ id: string }> {
    const client = this.createGraphqlClient(uniqueToken);
    const graphQLVariables = {
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

    const errorMessage = 'Invalid response from Unique API ingestion finalization';
    return await this.makeRateLimitedRequest(errorMessage, async () => {
      const result = await client.request<{ contentUpsert?: { id?: string } }>(
        this.getContentUpsertMutation(),
        graphQLVariables,
      );

      assert.ok(
        result?.contentUpsert?.id,
        'Invalid response from Unique API ingestion finalization',
      );
      return { id: result.contentUpsert.id };
    });
  }

  private async makeRateLimitedRequest<T>(
    errorMessage: string,
    requestFn: () => Promise<T>,
  ): Promise<T> {
    return await this.limiter.schedule(async () => {
      try {
        return await requestFn();
      } catch (error) {
        const normalizedError = normalizeError(error);
        this.logger.error(errorMessage, normalizedError.message);
        throw error;
      }
    });
  }

  private createGraphqlClient(uniqueToken: string): GraphQLClient {
    const graphqlUrl = this.configService.get('unique.ingestionGraphqlUrl', { infer: true });
    return new GraphQLClient(graphqlUrl, {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${uniqueToken}`,
        ...this.ingestionHttpExtraHeaders,
      },
    });
  }

  private getContentUpsertMutation(): string {
    return `
    mutation ContentUpsert(
      $input: ContentCreateInput!
      $fileUrl: String
      $chatId: String
      $scopeId: String
      $sourceOwnerType: String
      $sourceName: String
      $sourceKind: String
      $storeInternally: Boolean
      $baseUrl: String
    ) {
      contentUpsert(
        input: $input
        fileUrl: $fileUrl
        chatId: $chatId
        scopeId: $scopeId
        sourceOwnerType: $sourceOwnerType
        sourceName: $sourceName
        sourceKind: $sourceKind
        storeInternally: $storeInternally
        baseUrl: $baseUrl
      ) {
        id
        key
        title
        byteSize
        mimeType
        ownerType
        ownerId
        writeUrl
        readUrl
        createdAt
        internallyStoredAt
        source {
          kind
          name
        }
      }
    }
  `;
  }
}
