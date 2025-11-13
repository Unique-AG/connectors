import {Injectable, Logger} from '@nestjs/common';
import type {SharepointContentItem} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import {ItemProcessingOrchestratorService} from '../processing-pipeline/item-processing-orchestrator.service';
import {UniqueFileIngestionService} from '../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import type {
  FileDiffItem,
  FileDiffResponse,
} from '../unique-api/unique-file-ingestion/unique-file-ingestion.types';
import {UniqueFilesService} from '../unique-api/unique-files/unique-files.service';
import type {Scope} from '../unique-api/unique-scopes/unique-scopes.types';
import {buildFileDiffKey, getItemUrl} from '../utils/sharepoint.util';
import {elapsedSecondsLog} from '../utils/timing.util';
import {FileMoveProcessor} from './file-move-processor.service';
import {ScopeManagementService} from './scope-management.service';
import {UniqueFile} from "../unique-api/unique-files/unique-files.types";

@Injectable()
export class ContentSyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly orchestrator: ItemProcessingOrchestratorService,
    private readonly uniqueFileIngestionService: UniqueFileIngestionService,
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly fileMoveProcessor: FileMoveProcessor,
    private readonly scopeManagementService: ScopeManagementService,
  ) {
  }

  public async syncContentForSite(
    siteId: string,
    items: SharepointContentItem[],
    scopes?: Scope[],
  ): Promise<void> {
    const logPrefix = `[SiteId: ${ siteId }] `;
    const processStartTime = Date.now();

    const diffResult = await this.calculateDiffForSite(items, siteId);

    this.logger.log(
      `${ logPrefix } File Diff Results: ${ diffResult.newFiles.length } new, ${ diffResult.updatedFiles.length } updated, ${ diffResult.movedFiles.length } moved, ${ diffResult.deletedFiles.length } deleted`,
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
    const fileKeysToSync = new Set([...diffResult.newFiles, ...diffResult.updatedFiles]);
    if (fileKeysToSync.size === 0) {
      this.logger.log(`${ logPrefix } No new/updated files to sync`);
      return;
    }

    const itemsToSync = items.filter((item) => fileKeysToSync.has(item.item.id));

    // Build itemIdToScopeIdMap from scopes if in recursive mode
    let itemIdToScopeIdMap: Map<string, string> | undefined;
    if (scopes && scopes.length > 0) {
      itemIdToScopeIdMap = this.scopeManagementService.buildItemIdToScopeIdMap(itemsToSync, scopes);
    }

    await this.orchestrator.processItems(siteId, itemsToSync, itemIdToScopeIdMap);

    this.logger.log(
      `${ logPrefix } Finished processing all content operations in ${ elapsedSecondsLog(processStartTime) }`,
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
    const logPrefix = `[SiteId: ${ siteId }]`;
    let filesToDelete: UniqueFile[] = [];
    // Convert relative keys to full keys (with siteId prefix)
    // TODO: This works for files but does it work file sitePages aspx files?
    const fullKeys = deletedFileKeys.map((key) => `${ siteId }/${ key }`);

    try {
      // Get content that matches the exact keys
      filesToDelete = await this.uniqueFilesService.getFilesByKeys(fullKeys);
    } catch (error) {
      this.logger.error(`${ logPrefix } File deleted: ${ error }`);
      throw error;
    }

    // Delete each file
    let totalDeleted = 0;
    for (const file of filesToDelete) {
      try {
        await this.uniqueFilesService.deleteFile(file.id);
        totalDeleted++;
      } catch (error) {
        this.logger.error(
          `${ logPrefix } Failed to delete content ${ file.key } (ID: ${ file.id }):`,
          error,
        );
      }
    }

    this.logger.log(
      `${ logPrefix } Completed deletion processing: ${ totalDeleted } content items deleted for ${ deletedFileKeys.length } deleted files`,
    );
  }
}
