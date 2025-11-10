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
  IngestionMode,
} from '../constants/ingestion.constants';
import { UniqueOwnerType } from '../constants/unique-owner-type.enum';
import { UNIQUE_HTTP_CLIENT } from '../http-client.tokens';
import { normalizeError } from '../utils/normalize-error';
import { getScopeIdForIngestion } from './ingestion.util';
import {
  type ContentRegistrationRequest,
  type FileDiffItem,
  type FileDiffRequest,
  type FileDiffResponse,
  type IngestionApiResponse,
  type IngestionFinalizationRequest,
  type Scope,
} from './unique-api.types';

@Injectable()
export class UniqueApiService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly limiter: Bottleneck;
  private readonly ingestionMode: IngestionMode;
  private readonly scopeId: string | undefined;
  private readonly rootScopeName: string | undefined;
  private readonly fileDiffUrl: string;
  private readonly sharepointBaseUrl: string;
  private readonly ingestionGraphqlUrl: string;
  private readonly scopeManagementGraphqlUrl: string | undefined;
  private readonly apiRateLimitPerMinute: number;
  private readonly ingestionHttpExtraHeaders: Record<string, string>;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    @Inject(UNIQUE_HTTP_CLIENT) private readonly httpClient: Client,
  ) {
    this.ingestionMode = this.configService.get('unique.ingestionMode', { infer: true });
    this.scopeId = this.configService.get('unique.scopeId', { infer: true });
    this.rootScopeName = this.configService.get('unique.rootScopeName', { infer: true });
    this.fileDiffUrl = this.configService.get('unique.fileDiffUrl', { infer: true });
    this.sharepointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
    this.ingestionGraphqlUrl = this.configService.get('unique.ingestionGraphqlUrl', {
      infer: true,
    });
    this.scopeManagementGraphqlUrl = this.configService.get('unique.scopeManagementGraphqlUrl', {
      infer: true,
    });
    this.apiRateLimitPerMinute = this.configService.get('unique.apiRateLimitPerMinute', {
      infer: true,
    });
    this.ingestionHttpExtraHeaders =
      this.configService.get('unique.httpExtraHeaders', { infer: true }) || {};

    this.limiter = new Bottleneck({
      reservoir: this.apiRateLimitPerMinute,
      reservoirRefreshAmount: this.apiRateLimitPerMinute,
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
    const url = new URL(this.fileDiffUrl);
    const path = url.pathname + url.search;

    const basePath = this.rootScopeName || this.sharepointBaseUrl;

    const diffRequest: FileDiffRequest = {
      basePath,
      partialKey,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      fileList,
    };

    this.logger.debug(`File diff request payload: ${JSON.stringify(diffRequest, null, 2)}`);

    const errorMessage = 'File diff failed:';
    return await this.makeRateLimitedRequest(errorMessage, async () => {
      const { statusCode, body } = await this.httpClient.request({
        method: 'POST',
        path,
        headers: {
          ...this.ingestionHttpExtraHeaders,
          'Content-Type': 'application/json',
          Authorization: `Bearer ${uniqueToken}`,
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

  public async createScopesBasedOnPaths(paths: string[], uniqueToken: string): Promise<Scope[]> {
    if (!this.scopeManagementGraphqlUrl) {
      this.logger.warn('Scope management GraphQL URL not configured, skipping scope generation.');
      return [];
    }

    const client = this.createScopeManagementGraphqlClient(uniqueToken);
    const variables = {
      paths,
    };

    const errorMessage = 'Failed to generate scopes based on paths';
    return await this.makeRateLimitedRequest(errorMessage, async () => {
      const result = await client.request<{ generateScopesBasedOnPaths?: Scope[] }>(
        this.getGenerateScopesMutation(),
        variables,
      );

      assert.ok(
        result?.generateScopesBasedOnPaths,
        'Invalid response from Scope Management API scope generation',
      );
      return result.generateScopesBasedOnPaths;
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
    return new GraphQLClient(this.ingestionGraphqlUrl, {
      headers: {
        ...this.ingestionHttpExtraHeaders,
        'Content-Type': 'application/json',
        Authorization: `Bearer ${uniqueToken}`,
      },
    });
  }

  private createScopeManagementGraphqlClient(uniqueToken: string): GraphQLClient {
    assert(this.scopeManagementGraphqlUrl, 'Scope management GraphQL URL is not configured');
    return new GraphQLClient(this.scopeManagementGraphqlUrl, {
      headers: {
        ...this.ingestionHttpExtraHeaders,
        'Content-Type': 'application/json',
        Authorization: `Bearer ${uniqueToken}`,
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

  private getGenerateScopesMutation(): string {
    return `
    mutation GenerateScopesBasedOnPaths($paths: [String!]!) {
      generateScopesBasedOnPaths(paths: $paths) {
        id
        name
        parentId
      }
    }
  `;
  }
}
