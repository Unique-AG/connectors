import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { GraphQLClient } from 'graphql-request';
import { Client } from 'undici';
import { OwnerType } from '../constants/owner-type.enum';
import { UNIQUE_HTTP_CLIENT } from '../http-client.tokens';
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

  public constructor(
    private readonly configService: ConfigService,
    @Inject(UNIQUE_HTTP_CLIENT) private readonly httpClient: Client,
  ) {
    this.limiter = new Bottleneck({ maxConcurrent: 1, minTime: 50 });
  }

  public async registerContent(
    request: ContentRegistrationRequest,
    uniqueToken: string,
  ): Promise<IngestionApiResponse> {
    return await this.makeRateLimitedRequest(async () => {
      try {
        this.logger.log(`Content registration request object: ${JSON.stringify(request, null, 2)}`);
        const client = this.createGraphqlClient(uniqueToken);
        const variables = {
          input: {
            key: request.key,
            title: request.title,
            mimeType: request.mimeType,
            ownerType: OwnerType.SCOPE,
            url: request.url,
          },
          scopeId: request.scopeId,
          sourceOwnerType: request.sourceOwnerType,
          sourceKind: request.sourceKind,
          sourceName: request.sourceName,
          storeInternally: true,
          baseUrl: request.baseUrl,
        };

        this.logger.log(
          `Content registration request body variables: ${JSON.stringify(variables, null, 2)}`,
        );

        const result = await client.request<{ contentUpsert?: IngestionApiResponse }>(
          this.getContentUpsertMutation(),
          variables,
        );

        if (!result?.contentUpsert) {
          throw new Error('Invalid response from Unique API content registration');
        }

        return result.contentUpsert;
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
    const scopeId = this.configService.get<string | undefined>('uniqueApi.scopeId');
    const partialKey = <string>this.configService.get('uniqueApi.fileDiffPartialKey');
    const ingestionUrl = <string>this.configService.get('uniqueApi.ingestionUrl');
    const basePath = <string>this.configService.get('uniqueApi.fileDiffBasePath');
    const fileDiffUrl = `${ingestionUrl}/file-diff`;
    const url = new URL(fileDiffUrl);
    const path = url.pathname + url.search;

    const diffRequest: FileDiffRequest = {
      basePath,
      partialKey,
      sourceKind: 'MICROSOFT_365_SHAREPOINT',
      sourceName: 'SharePoint Online Connector',
      fileList,
      scope: scopeId ?? 'PATH',
    };

    return await this.makeRateLimitedRequest(async () => {
      try {
        const { statusCode, body } = await this.httpClient.request({
          method: 'POST',
          path,
          headers: {
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
    this.logger.log(`Ingestion finalization request object: ${JSON.stringify(request, null, 2)}`);

    const graphQLVariables = {
      input: {
        key: request.key,
        title: request.title,
        mimeType: request.mimeType,
        ownerType: OwnerType.SCOPE,
        byteSize: request.byteSize,
        url: request.url,
      },
      scopeId: request.scopeId,
      sourceOwnerType: request.sourceOwnerType,
      sourceName: request.sourceName,
      sourceKind: request.sourceKind,
      fileUrl: request.fileUrl,
      storeInternally: true,
      baseUrl: request.baseUrl,
    };

    return await this.makeRateLimitedRequest(async () => {
      try {
        const client = this.createGraphqlClient(uniqueToken);

        const result = await client.request<{ contentUpsert?: { id?: string } }>(
          this.getContentUpsertMutation(),
          graphQLVariables,
        );

        if (!result?.contentUpsert?.id) {
          throw new Error('Invalid response from Unique API ingestion finalization');
        }

        return { id: result.contentUpsert.id };
      } catch (error) {
        this.logger.error(
          `Ingestion finalization failed:`,
          error instanceof Error ? error.message : String(error),
        );
        throw error;
      }
    });
  }

  private async makeRateLimitedRequest<T>(requestFn: () => Promise<T>): Promise<T> {
    return await this.limiter.schedule(async () => await requestFn());
  }

  private createGraphqlClient(uniqueToken: string): GraphQLClient {
    const graphqlUrl = <string>this.configService.get('uniqueApi.ingestionGraphQLUrl');
    return new GraphQLClient(graphqlUrl, {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${uniqueToken}`,
      },
    });
  }

  private getContentUpsertMutation(): string {
    return `mutation ContentUpsert(
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
    source { kind name }
    }
    }`;
  }
}
