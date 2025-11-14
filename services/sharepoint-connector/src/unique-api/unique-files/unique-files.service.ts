import { Inject, Injectable, Logger } from '@nestjs/common';
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
  public constructor(
    @Inject(INGESTION_CLIENT) private readonly ingestionClient: UniqueGraphqlClient,
  ) {}

  public async moveFile(
    contentId: string,
    newOwnerId: string,
  ): Promise<ContentUpdateMutationResult['contentUpdate']> {
    this.logger.log(`Moving file ${contentId} to owner ${newOwnerId}`);

    const result = await this.ingestionClient.get(
      async (client) =>
        await client.request<ContentUpdateMutationResult, ContentUpdateMutationInput>(
          CONTENT_UPDATE_MUTATION,
          {
            contentId,
            ownerId: newOwnerId,
            input: {},
          },
        ),
    );

    return result.contentUpdate;
  }

  public async deleteFile(contentId: string): Promise<boolean> {
    this.logger.log(`Deleting file ${contentId}`);

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
