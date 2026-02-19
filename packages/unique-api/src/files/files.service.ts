import { getErrorCodeFromGraphqlRequest } from '@unique-ag/utils';
import { Logger } from '@nestjs/common';
import { chunk } from 'remeda';
import type { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import {
  ADD_ACCESSES_MUTATION,
  type AddAccessesMutationInput,
  type AddAccessesMutationResult,
  CONTENT_DELETE_BY_IDS_MUTATION,
  CONTENT_DELETE_MUTATION,
  CONTENT_ID_BY_SCOPE_AND_METADATA_KET,
  CONTENT_UPDATE_MUTATION,
  type ContentByScopeAndMetadataKeyInput,
  type ContentByScopeAndMetadataKeyResult,
  type ContentDeleteByContentIdsMutationInput,
  type ContentDeleteByContentIdsMutationResult,
  type ContentDeleteMutationInput,
  type ContentDeleteMutationResult,
  type ContentUpdateMutationInput,
  type ContentUpdateMutationResult,
  PAGINATED_CONTENT_COUNT_QUERY,
  PAGINATED_CONTENT_QUERY,
  type PaginatedContentCountQueryInput,
  type PaginatedContentCountQueryResult,
  type PaginatedContentQueryInput,
  type PaginatedContentQueryResult,
  REMOVE_ACCESSES_MUTATION,
  type RemoveAccessesMutationInput,
  type RemoveAccessesMutationResult,
} from './files.queries';
import type { ContentUpdateResult, FileAccessInput, UniqueFile } from './files.types';
import { UniqueFilesFacade } from './unique-files.facade';

const CONTENT_BATCH_SIZE = 100;
const DELETE_BATCH_SIZE = 20;

// We decide for this batch size because on the Unique side, for each permission requested we make a
// concurrent call to node-ingestion and further to Zitadel, so we want to avoid overwhelming the
// system when we have a huge folder with many files.
const ACCESS_BATCH_SIZE = 20;

export class FilesService implements UniqueFilesFacade {
  public constructor(
    private readonly ingestionClient: UniqueGraphqlClient,
    private readonly logger: Logger,
  ) {}

  public async getByKeys(keys: string[]): Promise<UniqueFile[]> {
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

  public async getByKeyPrefix(keyPrefix: string): Promise<UniqueFile[]> {
    this.logger.log(`[KeyPrefix: ${keyPrefix}] Fetching files`);

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
            startsWith: `${keyPrefix}/`,
          },
        },
      });
      files.push(...batchResult.paginatedContent.nodes);
      batchCount = batchResult.paginatedContent.nodes.length;
      skip += CONTENT_BATCH_SIZE;
    } while (batchCount === CONTENT_BATCH_SIZE);

    return files;
  }

  public async getCountByKeyPrefix(keyPrefix: string): Promise<number> {
    this.logger.debug(`[KeyPrefix: ${keyPrefix}] Fetching files count`);

    const result = await this.ingestionClient.request<
      PaginatedContentCountQueryResult,
      PaginatedContentCountQueryInput
    >(PAGINATED_CONTENT_COUNT_QUERY, {
      where: {
        key: {
          startsWith: `${keyPrefix}/`,
        },
      },
    });

    return result.paginatedContent.totalCount;
  }

  public async move(
    contentId: string,
    newOwnerId: string,
    newUrl: string,
  ): Promise<ContentUpdateResult> {
    this.logger.debug(`[ContentId: ${contentId}] Moving file to owner ${newOwnerId}`);

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

  public async delete(contentId: string): Promise<boolean> {
    this.logger.debug(`[ContentId: ${contentId}] Deleting file`);

    const result = await this.ingestionClient.request<
      ContentDeleteMutationResult,
      ContentDeleteMutationInput
    >(CONTENT_DELETE_MUTATION, {
      contentDeleteId: contentId,
    });

    return result.contentDelete;
  }

  public async deleteByIds(contentIds: string[]): Promise<number> {
    const logPrefix = `[Delete Contents]`;

    let totalDeleted = 0;
    const deleteBatches = chunk(contentIds, DELETE_BATCH_SIZE);
    for (const deleteBatch of deleteBatches) {
      await this.ingestionClient.request<
        ContentDeleteByContentIdsMutationResult,
        ContentDeleteByContentIdsMutationInput
      >(CONTENT_DELETE_BY_IDS_MUTATION, {
        contentIds: deleteBatch,
      });

      totalDeleted += deleteBatch.length;
      this.logger.debug(
        `${logPrefix} Deleted batch of ${deleteBatch.length} files (Total: ${totalDeleted})`,
      );
    }

    return totalDeleted;
  }

  public async deleteByKeyPrefix(keyPrefix: string): Promise<number> {
    const logPrefix = `[KeyPrefix: ${keyPrefix}]`;
    this.logger.log(`${logPrefix} Starting iterative file deletion`);

    let totalDeleted = 0;
    let hasMore = true;

    while (hasMore) {
      const batchResult = await this.ingestionClient.request<
        PaginatedContentQueryResult,
        PaginatedContentQueryInput
      >(PAGINATED_CONTENT_QUERY, {
        skip: 0,
        take: CONTENT_BATCH_SIZE,
        where: {
          key: {
            startsWith: `${keyPrefix}/`,
          },
        },
      });

      const fileIds = batchResult.paginatedContent.nodes.map((f) => f.id);

      if (fileIds.length === 0) {
        hasMore = false;
        continue;
      }

      const deleteBatches = chunk(fileIds, DELETE_BATCH_SIZE);
      for (const deleteBatch of deleteBatches) {
        await this.ingestionClient.request<
          ContentDeleteByContentIdsMutationResult,
          ContentDeleteByContentIdsMutationInput
        >(CONTENT_DELETE_BY_IDS_MUTATION, {
          contentIds: deleteBatch,
        });

        totalDeleted += deleteBatch.length;
        this.logger.debug(
          `${logPrefix} Deleted batch of ${deleteBatch.length} files (Total: ${totalDeleted})`,
        );
      }
    }

    this.logger.log(
      `${logPrefix} Iterative file deletion completed. Total deleted: ${totalDeleted}`,
    );
    return totalDeleted;
  }

  public async addAccesses(scopeId: string, fileAccesses: FileAccessInput[]): Promise<number> {
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
            this.logger.error(
              {
                msg: `${logPrefix} Failed to add single file access`,
                scopeId,
                permission,
              },
              singleError,
            );
          }
        }
      }
    }

    return successCount;
  }

  public async removeAccesses(scopeId: string, fileAccesses: FileAccessInput[]): Promise<number> {
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
            this.logger.error(
              {
                msg: `${logPrefix} Failed to remove single file access`,
                scopeId,
                permission,
              },
              singleError,
            );
          }
        }
      }
    }

    return successCount;
  }

  public async getIdsByScopeAndMetadataKey(
    scopeId: string,
    metadataKey: string,
    metadataValue: unknown,
  ): Promise<string[]> {
    const result = await this.ingestionClient.request<
      ContentByScopeAndMetadataKeyResult,
      ContentByScopeAndMetadataKeyInput
    >(CONTENT_ID_BY_SCOPE_AND_METADATA_KET, {
      scopeId,
      metadataKey,
      metadataValue,
    });

    return result.content.map((item) => item?.id);
  }
}
