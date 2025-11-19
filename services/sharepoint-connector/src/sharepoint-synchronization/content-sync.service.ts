import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { ItemProcessingOrchestratorService } from '../processing-pipeline/item-processing-orchestrator.service';
import { UniqueFileIngestionService } from '../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import type {
  FileDiffItem,
  FileDiffResponse,
} from '../unique-api/unique-file-ingestion/unique-file-ingestion.types';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import { UniqueFile } from '../unique-api/unique-files/unique-files.types';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { normalizeError } from '../utils/normalize-error';
import { buildFileDiffKey, getItemUrl } from '../utils/sharepoint.util';
import { elapsedSecondsLog } from '../utils/timing.util';
import { FileMoveProcessor } from './file-move-processor.service';
import { ScopeManagementService } from './scope-management.service';

@Injectable()
export class ContentSyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly orchestrator: ItemProcessingOrchestratorService,
    private readonly uniqueFileIngestionService: UniqueFileIngestionService,
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly fileMoveProcessor: FileMoveProcessor,
    private readonly scopeManagementService: ScopeManagementService,
  ) {}

  public async syncContentForSite(
    siteId: string,
    items: SharepointContentItem[],
    scopes: ScopeWithPath[] | null,
  ): Promise<void> {
    const logPrefix = `[SiteId: ${siteId}] `;
    const processStartTime = Date.now();

    const diffResult = await this.calculateDiffForSite(items, siteId);

    this.logger.log(
      `${logPrefix} File Diff Results: ${diffResult.newFiles.length} new, ${diffResult.updatedFiles.length} updated, ${diffResult.movedFiles.length} moved, ${diffResult.deletedFiles.length} deleted`,
    );

    // 1. Delete removed files first
    if (diffResult.deletedFiles.length > 0) {
      await this.deleteRemovedFiles(siteId, diffResult.deletedFiles);
    }

    // 2. Handle moved files (update scopes)
    if (diffResult.movedFiles.length > 0) {
      await this.fileMoveProcessor.processFileMoves(siteId, diffResult.movedFiles, items, scopes);
    }

    // 3. Process new/updated files
    const newFileKeys = new Set(diffResult.newFiles);
    const updatedFileKeys = new Set(diffResult.updatedFiles);

    const totalFilesToIngest = newFileKeys.size + updatedFileKeys.size;
    const maxIngestedFiles = this.configService.get('unique.maxIngestedFiles', { infer: true });

    assert.ok(
      maxIngestedFiles === undefined || totalFilesToIngest <= maxIngestedFiles,
      `${logPrefix} Too many files to ingest: ${totalFilesToIngest}. Limit is ${maxIngestedFiles}. Aborting sync.`,
    );

    if (newFileKeys.size === 0 && updatedFileKeys.size === 0) {
      this.logger.log(`${logPrefix} No new/updated files to sync`);
      return;
    }

    const newItems = items.filter((item) => newFileKeys.has(item.item.id));
    const updatedItems = items.filter((item) => updatedFileKeys.has(item.item.id));

    const configuredScopeId = this.configService.get('unique.scopeId', { infer: true });

    const getScopeIdForItem = (itemId: string): string => {
      const scopeId = configuredScopeId ?? ''; // if scopes is empty and we got here it means we are in flat mode and scopeId is required

      if (!scopes || scopes.length === 0) {
        return scopeId;
      }

      const item = [...newItems, ...updatedItems].find((item) => item.item.id === itemId);
      if (!item) {
        this.logger.warn(
          `${logPrefix} Cannot determine scope for item because item with id: ${itemId} not found`,
        );
        return scopeId;
      }
      return this.scopeManagementService.determineScopeForItem(item, scopes) || scopeId;
    };

    await this.orchestrator.processItems(siteId, newItems, updatedItems, getScopeIdForItem);

    this.logger.log(
      `${logPrefix} Finished processing all content operations in ${elapsedSecondsLog(processStartTime)}`,
    );
  }

  private async calculateDiffForSite(
    sharepointContentItems: SharepointContentItem[],
    siteId: string,
  ): Promise<FileDiffResponse> {
    const fileDiffItems: FileDiffItem[] = sharepointContentItems.map(
      (sharepointContentItem: SharepointContentItem) => {
        const key = buildFileDiffKey(sharepointContentItem);

        return {
          key,
          url: getItemUrl(sharepointContentItem),
          updatedAt: sharepointContentItem.item.lastModifiedDateTime,
        };
      },
    );

    return await this.uniqueFileIngestionService.performFileDiff(fileDiffItems, siteId);
  }

  private async deleteRemovedFiles(siteId: string, deletedFileKeys: string[]): Promise<void> {
    const logPrefix = `[SiteId: ${siteId}]`;
    let filesToDelete: UniqueFile[] = [];
    // Convert relative keys to full keys (with siteId prefix)
    const fullKeys = deletedFileKeys.map((key) => `${siteId}/${key}`);

    try {
      // Get content that matches the exact keys
      filesToDelete = await this.uniqueFilesService.getFilesByKeys(fullKeys);
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error({
        msg: `${logPrefix} Failed to get content for deleted files, cannot delete ${deletedFileKeys.length} ingested files: ${normalizedError.message}`,
        error,
      });
      return;
    }

    // Delete each file
    let totalDeleted = 0;
    for (const file of filesToDelete) {
      try {
        await this.uniqueFilesService.deleteFile(file.id);
        totalDeleted++;
      } catch (error) {
        const normalizedError = normalizeError(error);
        this.logger.error({
          msg: `${logPrefix} Failed to delete content ${file.key} (ID: ${file.id}): ${normalizedError.message}`,
          error,
        });
      }
    }

    this.logger.log(
      `${logPrefix} Completed file deletion in Unique: ${totalDeleted}/${deletedFileKeys.length} files deleted files`,
    );
  }
}
