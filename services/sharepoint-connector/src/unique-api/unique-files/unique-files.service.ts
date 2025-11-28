import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { shouldConcealLogs, smear } from '../../utils/logging.util';
import { INGESTION_CLIENT, UniqueGraphqlClient } from '../clients/unique-graphql.client';
import {
  ADD_ACCESSES_MUTATION,
  AddAccessesMutationInput,
  AddAccessesMutationResult,
  CONTENT_DELETE_MUTATION,
  CONTENT_UPDATE_MUTATION,
  ContentDeleteMutationInput,
  ContentDeleteMutationResult,
  ContentUpdateMutationInput,
  ContentUpdateMutationResult,
  PAGINATED_CONTENT_QUERY,
  PaginatedContentQueryInput,
  PaginatedContentQueryResult,
  REMOVE_ACCESSES_MUTATION,
  RemoveAccessesMutationInput,
  RemoveAccessesMutationResult,
} from './unique-files.consts';
import { UniqueFile, UniqueFileAccessInput } from './unique-files.types';

const BATCH_SIZE = 100;

@Injectable()
export class UniqueFilesService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly shouldConcealLogs: boolean;
  public constructor(
    @Inject(INGESTION_CLIENT) private readonly ingestionClient: UniqueGraphqlClient,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

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

  public async getFilesByKeys(keys: string[]): Promise<UniqueFile[]> {
    if (keys.length === 0) {
      return [];
    }

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
                  in: keys,
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

  public async getFilesForSite(siteId: string): Promise<UniqueFile[]> {
    const logPrefix = `[SiteId: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
    this.logger.log(`${logPrefix} Fetching files`);

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

  public async addAccesses(scopeId: string, fileAccesses: UniqueFileAccessInput[]): Promise<void> {
    await this.ingestionClient.get(async (client) => {
      await client.request<AddAccessesMutationResult, AddAccessesMutationInput>(
        ADD_ACCESSES_MUTATION,
        {
          scopeId,
          fileAccesses,
        },
      );
    });
  }

  public async removeAccesses(
    scopeId: string,
    fileAccesses: UniqueFileAccessInput[],
  ): Promise<void> {
    await this.ingestionClient.get(async (client) => {
      await client.request<RemoveAccessesMutationResult, RemoveAccessesMutationInput>(
        REMOVE_ACCESSES_MUTATION,
        {
          scopeId,
          fileAccesses,
        },
      );
    });
  }
}
