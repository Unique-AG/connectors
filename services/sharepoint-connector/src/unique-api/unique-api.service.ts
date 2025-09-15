import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { Client } from 'undici';
import { UNIQUE_HTTP_CLIENT } from '../http-client.tokens';
import {
  type ContentRegistrationRequest,
  type FileDiffItem,
  type FileDiffRequest,
  type FileDiffResponse,
  type IngestionApiResponse,
  type IngestionFinalizationRequest,
} from './types/unique-api.types';

@Injectable()
export class UniqueApiService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly limiter: Bottleneck;

  public constructor(
    private readonly configService: ConfigService,
    @Inject(UNIQUE_HTTP_CLIENT) private readonly httpClient: Client,
  ) {
    this.limiter = new Bottleneck({ maxConcurrent: 1, minTime: 50 });
  }

  private async makeRateLimitedRequest<T>(requestFn: () => Promise<T>): Promise<T> {
    return await this.limiter.schedule(async () => await requestFn());
  }

  public async registerContent(
    request: ContentRegistrationRequest,
    uniqueToken: string,
  ): Promise<IngestionApiResponse> {
    return await this.makeRateLimitedRequest(async () => {
      try {
        // GraphQL call without codegen - build request manually
        const graphqlUrl = this.configService.get<string>('uniqueApi.ingestionGraphQLUrl') ?? '';
        const url = new URL(graphqlUrl);
        const path = url.pathname + url.search;
        const query = `mutation ContentUpsert($input: ContentCreateInput!, $fileUrl: String, $chatId: String, $scopeId: String, $sourceOwnerType: String, $sourceName: String, $sourceKind: String, $storeInternally: Boolean) {\n  contentUpsert(input: $input, fileUrl: $fileUrl, chatId: $chatId, scopeId: $scopeId, sourceOwnerType: $sourceOwnerType, sourceName: $sourceName, sourceKind: $sourceKind, storeInternally: $storeInternally) {\n    id\n    key\n    byteSize\n    mimeType\n    ownerType\n    ownerId\n    writeUrl\n    readUrl\n    createdAt\n    internallyStoredAt\n    source {\n      kind\n      name\n    }\n  }\n}`;
        const variables = {
          input: {
            key: request.key,
            mimeType: request.mimeType,
            ownerType: request.ownerType,
          },
          scopeId: request.scopeId,
          sourceOwnerType: request.sourceOwnerType,
          sourceKind: request.sourceKind,
          sourceName: request.sourceName,
          storeInternally: true,
        };

        const { body } = await this.httpClient.request({
          method: 'POST',
          path,
          headers: {
            'content-type': 'application/json',
            Authorization: `Bearer ${uniqueToken}`,
          },
          body: JSON.stringify({ query, variables }),
          throwOnError: true,
        });

        const responseData = (await body.json()) as {
          data?: { contentUpsert?: IngestionApiResponse };
          errors?: unknown;
        };
        const result = responseData?.data?.contentUpsert;
        if (!result) {
          throw new Error('Invalid response from Unique API content registration');
        }
        return result;
      } catch (error) {
        this.logger.error(
          'Content registration failed:',
          error instanceof Error ? error.message : String(error),
        );
        throw error;
      }
    });
  }

  public async performFileDiff(
    fileList: FileDiffItem[],
    uniqueToken: string,
  ): Promise<FileDiffResponse> {
    return await this.makeRateLimitedRequest(async () => {
      const ingestionUrl = this.configService.get<string>('uniqueApi.ingestionUrl') ?? '';
      const fileDiffUrl = `${ingestionUrl}/file-diff`;
      const scopeId = this.configService.get<string>('uniqueApi.scopeId') ?? 'unknown-scope';
      const basePath =
        this.configService.get<string>('uniqueApi.fileDiffBasePath') ??
        'https://next.qa.unique.app/';
      const partialKey =
        this.configService.get<string>('uniqueApi.fileDiffPartialKey') ?? 'sharepoint/default';

      const diffRequest: FileDiffRequest = {
        basePath,
        partialKey,
        sourceKind: 'MICROSOFT_365_SHAREPOINT',
        sourceName: 'SharePoint Online Connector',
        fileList,
        scope: scopeId,
      };

      try {
        const url = new URL(fileDiffUrl);
        const path = url.pathname + url.search;
        const { body } = await this.httpClient.request({
          method: 'POST',
          path,
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${uniqueToken}`,
          },
          body: JSON.stringify(diffRequest),
          throwOnError: true,
        });
        const responseData = await body.json();
        if (!responseData) {
          throw new Error('Invalid response from Unique API file diff');
        }
        return responseData as FileDiffResponse;
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        this.logger.error('File diff failed:', errorMessage);
        throw error;
      }
    });
  }

  public async finalizeIngestion(
    request: IngestionFinalizationRequest,
    uniqueToken: string,
  ): Promise<{ id: string }> {
    return await this.makeRateLimitedRequest(async () => {
      try {
        const graphqlUrl = this.configService.get<string>('uniqueApi.ingestionGraphQLUrl') ?? '';
        const url = new URL(graphqlUrl);
        const path = url.pathname + url.search;
        const query = `mutation ContentUpsert($input: ContentCreateInput!, $fileUrl: String, $chatId: String, $scopeId: String, $sourceOwnerType: String, $sourceName: String, $sourceKind: String, $storeInternally: Boolean) {\n  contentUpsert(input: $input, fileUrl: $fileUrl, chatId: $chatId, scopeId: $scopeId, sourceOwnerType: $sourceOwnerType, sourceName: $sourceName, sourceKind: $sourceKind, storeInternally: $storeInternally) {\n    id\n    key\n    byteSize\n    mimeType\n    ownerType\n    ownerId\n    writeUrl\n    readUrl\n    createdAt\n    internallyStoredAt\n    source {\n      kind\n      name\n    }\n  }\n}`;
        const variables = {
          input: {
            key: request.key,
            mimeType: request.mimeType,
            ownerType: request.ownerType,
            byteSize: request.byteSize,
          },
          scopeId: request.scopeId,
          sourceOwnerType: request.sourceOwnerType,
          sourceName: request.sourceName,
          sourceKind: request.sourceKind,
          fileUrl: request.fileUrl,
          storeInternally: true,
        };

        const { body } = await this.httpClient.request({
          method: 'POST',
          path,
          headers: {
            'content-type': 'application/json',
            Authorization: `Bearer ${uniqueToken}`,
          },
          body: JSON.stringify({ query, variables }),
          throwOnError: true,
        });

        const responseData = (await body.json()) as { data?: { contentUpsert?: { id: string } } };
        const id = responseData?.data?.contentUpsert?.id;
        if (!id) {
          throw new Error('Invalid response from Unique API ingestion finalization');
        }
        return { id };
      } catch (error) {
        this.logger.error(
          'Ingestion finalization failed:',
          error instanceof Error ? error.message : String(error),
        );
        throw error;
      }
    });
  }
}
