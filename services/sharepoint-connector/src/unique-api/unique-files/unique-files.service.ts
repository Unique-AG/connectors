import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { chunk } from 'remeda';
import { Config } from '../../config';
import { getErrorCodeFromGraphqlRequest } from '../../utils/graphql-error.util';
import { shouldConcealLogs, smear } from '../../utils/logging.util';
import { sanitizeError } from '../../utils/normalize-error';
import { INGESTION_CLIENT, UniqueGraphqlClient } from '../clients/unique-graphql.client';
import {
  ADD_ACCESSES_MUTATION,
  AddAccessesMutationInput,
  AddAccessesMutationResult,
  CONTENT_DELETE_BY_IDS_MUTATION,
  CONTENT_DELETE_MUTATION,
  CONTENT_UPDATE_MUTATION,
  ContentDeleteByContentIdsMutationInput,
  ContentDeleteByContentIdsMutationResult,
  ContentDeleteMutationInput,
  ContentDeleteMutationResult,
  ContentUpdateMutationInput,
  ContentUpdateMutationResult,
  PAGINATED_CONTENT_COUNT_QUERY,
  PAGINATED_CONTENT_QUERY,
  PaginatedContentCountQueryInput,
  PaginatedContentCountQueryResult,
  PaginatedContentQueryInput,
  PaginatedContentQueryResult,
  REMOVE_ACCESSES_MUTATION,
  RemoveAccessesMutationInput,
  RemoveAccessesMutationResult,
} from './unique-files.consts';
import { UniqueFile, UniqueFileAccessInput } from './unique-files.types';

const CONTENT_BATCH_SIZE = 50;

// We decide for this batch size because on the Unique side, for each permission requested we make a
// concurrent call to node-ingestion and further to Zitadel, so we want to avoid overwhelming the
// system when we have a huge folder with many files.
const ACCESS_BATCH_SIZE = 20;

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
    const logPrefix = `[ContentId: ${contentId}]`;
    this.logger.debug(`${logPrefix} Moving file to owner ${newOwnerId}`);

    const result = await this.ingestionClient.request<
      ContentUpdateMutationResult,
      ContentUpdateMutationInput
    >(CONTENT_UPDATE_MUTATION, {
      contentId,
      ownerId: newOwnerId,
      input: { url: newUrl },
    });

    return result.contentUpdate;
  }

  public async deleteFile(contentId: string): Promise<boolean> {
    const logPrefix = `[ContentId: ${contentId}]`;
    this.logger.debug(`${logPrefix} Deleting file`);

    const result = await this.ingestionClient.request<
      ContentDeleteMutationResult,
      ContentDeleteMutationInput
    >(CONTENT_DELETE_MUTATION, {
      contentDeleteId: contentId,
    });

    return result.contentDelete;
  }

  public async deleteContentByContentIds(contentIds: string[]): Promise<void> {
    if (contentIds.length === 0) {
      return;
    }

    const chunkedContentIds = chunk(contentIds, CONTENT_BATCH_SIZE);

    this.logger.debug({
      msg: 'Starting batch content deletion',
      totalItems: contentIds.length,
      batchChunks: chunkedContentIds.length,
    });

    for (const [chunkIndex, contentIdsChunk] of chunkedContentIds.entries()) {
      this.logger.debug({
        msg: 'Executing batch content deletion chunk',
        chunkIndex: chunkIndex + 1,
        totalChunks: chunkedContentIds.length,
        itemsInChunk: contentIdsChunk.length,
      });

      await this.ingestionClient.request<
        ContentDeleteByContentIdsMutationResult,
        ContentDeleteByContentIdsMutationInput
      >(CONTENT_DELETE_BY_IDS_MUTATION, {
        contentIds: contentIdsChunk,
      });
    }

    this.logger.debug({
      msg: 'Batch content deletion completed',
      totalItems: contentIds.length,
    });
  }

  public async getFilesByKeys(keys: string[]): Promise<UniqueFile[]> {
    if (keys.length === 0) {
      return [];
    }

    let skip = 0;
    const files: UniqueFile[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.ingestionClient.request<
        PaginatedContentQueryResult,
        PaginatedContentQueryInput
      >(PAGINATED_CONTENT_QUERY, {
        skip,
        take: CONTENT_BATCH_SIZE,
        where: {
          key: {
            in: keys,
          },
        },
      });
      files.push(...batchResult.paginatedContent.nodes);
      batchCount = batchResult.paginatedContent.nodes.length;
      skip += CONTENT_BATCH_SIZE;
    } while (batchCount === CONTENT_BATCH_SIZE);

    return files;
  }

  public async getFilesForSite(siteId: string): Promise<UniqueFile[]> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
    this.logger.log(`${logPrefix} Fetching files`);

    let skip = 0;
    const files: UniqueFile[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.ingestionClient.request<
        PaginatedContentQueryResult,
        PaginatedContentQueryInput
      >(PAGINATED_CONTENT_QUERY, {
        skip,
        take: CONTENT_BATCH_SIZE,
        where: {
          key: {
            startsWith: `${siteId}/`,
          },
        },
      });
      files.push(...batchResult.paginatedContent.nodes);
      batchCount = batchResult.paginatedContent.nodes.length;
      skip += CONTENT_BATCH_SIZE;
    } while (batchCount === CONTENT_BATCH_SIZE);

    return files;
  }

  public async getFilesCountForSite(siteId: string): Promise<number> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
    this.logger.debug(`${logPrefix} Fetching files count`);

    const result = await this.ingestionClient.request<
      PaginatedContentCountQueryResult,
      PaginatedContentCountQueryInput
    >(PAGINATED_CONTENT_COUNT_QUERY, {
      where: {
        key: {
          startsWith: `${siteId}/`,
        },
      },
    });

    return result.paginatedContent.totalCount;
  }

  // We may encounter 400 errors when adding permissions to Unique, we encountered some cases where
  // users do not have sufficient permissions to be even given file permissions. For that reason we
  // retry one-by-one after 400 failure to pinpoint the exact user that is causing the issue and
  // ensure the rest is handled as expected.
  public async addAccesses(
    scopeId: string,
    fileAccesses: UniqueFileAccessInput[],
  ): Promise<number> {
    if (fileAccesses.length === 0) {
      return 0;
    }

    const logPrefix = `[Scope: ${scopeId}]`;
    const batches = chunk(fileAccesses, ACCESS_BATCH_SIZE);
    let successCount = 0;

    for (const batch of batches) {
      try {
        await this.ingestionClient.request<AddAccessesMutationResult, AddAccessesMutationInput>(
          ADD_ACCESSES_MUTATION,
          {
            scopeId,
            fileAccesses: batch,
          },
        );
        successCount += batch.length;
      } catch (error) {
        const statusCode = getErrorCodeFromGraphqlRequest(error);

        if (statusCode !== 400) {
          throw error;
        }

        this.logger.warn({
          msg: `${logPrefix} Failed to batch add file accesses, retrying one-by-one`,
          scopeId,
          batchSize: batch.length,
          statusCode,
        });

        for (const permission of batch) {
          try {
            await this.ingestionClient.request<AddAccessesMutationResult, AddAccessesMutationInput>(
              ADD_ACCESSES_MUTATION,
              {
                scopeId,
                fileAccesses: [permission],
              },
            );
            successCount += 1;
          } catch (singleError) {
            this.logger.error({
              msg: `${logPrefix} Failed to add single file access`,
              scopeId,
              permission,
              error: sanitizeError(singleError),
            });
          }
        }
      }
    }

    return successCount;
  }

  public async removeAccesses(
    scopeId: string,
    fileAccesses: UniqueFileAccessInput[],
  ): Promise<number> {
    if (fileAccesses.length === 0) {
      return 0;
    }

    const logPrefix = `[Scope: ${scopeId}]`;
    const batches = chunk(fileAccesses, ACCESS_BATCH_SIZE);
    let successCount = 0;

    for (const batch of batches) {
      try {
        await this.ingestionClient.request<
          RemoveAccessesMutationResult,
          RemoveAccessesMutationInput
        >(REMOVE_ACCESSES_MUTATION, {
          scopeId,
          fileAccesses: batch,
        });
        successCount += batch.length;
      } catch (error) {
        const statusCode = getErrorCodeFromGraphqlRequest(error);

        if (statusCode !== 400) {
          throw error;
        }

        this.logger.warn({
          msg: `${logPrefix} Failed to batch remove file accesses, retrying one-by-one`,
          scopeId,
          batchSize: batch.length,
          statusCode,
        });

        for (const permission of batch) {
          try {
            await this.ingestionClient.request<
              RemoveAccessesMutationResult,
              RemoveAccessesMutationInput
            >(REMOVE_ACCESSES_MUTATION, {
              scopeId,
              fileAccesses: [permission],
            });
            successCount += 1;
          } catch (singleError) {
            this.logger.error({
              msg: `${logPrefix} Failed to remove single file access`,
              scopeId,
              permission,
              error: sanitizeError(singleError),
            });
          }
        }
      }
    }

    return successCount;
  }
}
