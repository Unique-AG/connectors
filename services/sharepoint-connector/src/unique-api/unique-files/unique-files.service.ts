import { Injectable, Logger } from '@nestjs/common';
import { IngestionClient } from '../clients/ingestion.client';
import {
  CONTENT_BY_KEYS_QUERY,
  CONTENT_DELETE_MUTATION,
  CONTENT_UPDATE_MUTATION,
  ContentByKeysQueryInput,
  ContentByKeysQueryResult,
  ContentDeleteMutationInput,
  ContentDeleteMutationResult,
  ContentUpdateMutationInput,
  ContentUpdateMutationResult,
  PAGINATED_CONTENT_QUERY,
  PaginatedContentQueryInput,
  PaginatedContentQueryResult,
} from './unique-files.consts';
import { UniqueFile } from './unique-files.types';

const BATCH_SIZE = 100;

@Injectable()
export class UniqueFilesService {
  private readonly logger = new Logger(this.constructor.name);
  public constructor(private readonly ingestionClient: IngestionClient) {}

  public async moveFile(
    contentId: string,
    newOwnerId: string,
    newUrl: string,
  ): Promise<ContentUpdateMutationResult['contentUpdate']> {
    this.logger.debug(`Moving file ${contentId} to owner ${newOwnerId}`);

    const result = await this.ingestionClient.get(
      async (client) =>
        await client.request<ContentUpdateMutationResult, ContentUpdateMutationInput>(
          CONTENT_UPDATE_MUTATION,
          {
            contentId,
            ownerId: newOwnerId,
            input: { url: newUrl },
          },
        ),
    );

    return result.contentUpdate;
  }

  public async deleteFile(contentId: string): Promise<boolean> {
    this.logger.debug(`Deleting file ${contentId}`);

    const result = await this.ingestionClient.get(
      async (client) =>
        await client.request<ContentDeleteMutationResult, ContentDeleteMutationInput>(
          CONTENT_DELETE_MUTATION,
          {
            contentDeleteId: contentId,
          },
        ),
    );

    return result.contentDelete;
  }

  public async getFilesByKey(keys: string[]): Promise<UniqueFile[]> {
    if (keys.length === 0) {
      return [];
    }

    const result = await this.ingestionClient.get(
      async (client) =>
        await client.request<ContentByKeysQueryResult, ContentByKeysQueryInput>(
          CONTENT_BY_KEYS_QUERY,
          {
            where: {
              key: {
                in: keys,
              },
            },
          },
        ),
    );

    return result.contentByKeys;
  }

  public async getFilesForSite(siteId: string): Promise<UniqueFile[]> {
    this.logger.log(`Fetching files for site ${siteId}`);

    let skip = 0;
    const files: UniqueFile[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.ingestionClient.get(
        async (client) =>
          await client.request<PaginatedContentQueryResult, PaginatedContentQueryInput>(
            PAGINATED_CONTENT_QUERY,
            {
              skip,
              take: BATCH_SIZE,
              where: {
                key: {
                  startsWith: `${siteId}/`,
                },
              },
            },
          ),
      );
      files.push(...batchResult.paginatedContent.nodes);
      batchCount = batchResult.paginatedContent.nodes.length;
      skip += BATCH_SIZE;
    } while (batchCount === BATCH_SIZE);

    return files;
  }
}
