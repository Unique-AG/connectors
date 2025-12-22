import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Counter } from '@opentelemetry/api';
import { length, mapValues } from 'remeda';
import { Config } from '../config';
import { SPC_FILE_DELETED_TOTAL, SPC_FILE_DIFF_EVENTS_TOTAL } from '../metrics';
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
import { shouldConcealLogs, smear } from '../utils/logging.util';
import { sanitizeError } from '../utils/normalize-error';
import { buildFileDiffKey, getItemUrl } from '../utils/sharepoint.util';
import { elapsedSecondsLog } from '../utils/timing.util';
import { FileMoveProcessor } from './file-move-processor.service';
import { ScopeManagementService } from './scope-management.service';
import type { SharepointSyncContext } from './types';

@Injectable()
export class ContentSyncService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly orchestrator: ItemProcessingOrchestratorService,
    private readonly uniqueFileIngestionService: UniqueFileIngestionService,
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly fileMoveProcessor: FileMoveProcessor,
    private readonly scopeManagementService: ScopeManagementService,
    @Inject(SPC_FILE_DIFF_EVENTS_TOTAL) private readonly spcFileDiffEventsTotal: Counter,
    @Inject(SPC_FILE_DELETED_TOTAL) private readonly spcFileDeletedTotal: Counter,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

  public async syncContentForSite(
    items: SharepointContentItem[],
    scopes: ScopeWithPath[] | null,
    context: SharepointSyncContext,
  ): Promise<void> {
    const { siteId } = context;
    const logSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
    const logPrefix = `[Site: ${logSiteId}] `;
    const processStartTime = Date.now();

    const diffResult = await this.calculateDiffForSite(items, siteId);

    if (diffResult.newFiles.length > 0) {
      this.spcFileDiffEventsTotal.add(diffResult.newFiles.length, {
        sp_site_id: logSiteId,
        diff_result_type: 'new',
      });
    }
    if (diffResult.updatedFiles.length > 0) {
      this.spcFileDiffEventsTotal.add(diffResult.updatedFiles.length, {
        sp_site_id: logSiteId,
        diff_result_type: 'updated',
      });
    }
    if (diffResult.movedFiles.length > 0) {
      this.spcFileDiffEventsTotal.add(diffResult.movedFiles.length, {
        sp_site_id: logSiteId,
        diff_result_type: 'moved',
      });
    }
    if (diffResult.deletedFiles.length > 0) {
      this.spcFileDiffEventsTotal.add(diffResult.deletedFiles.length, {
        sp_site_id: logSiteId,
        diff_result_type: 'deleted',
      });
    }

    this.logger.log(
      `${logPrefix} File Diff Results: ${diffResult.newFiles.length} new, ${diffResult.updatedFiles.length} updated, ${diffResult.movedFiles.length} moved, ${diffResult.deletedFiles.length} deleted`,
    );

    // 1. Delete removed files first
    if (diffResult.deletedFiles.length > 0) {
      await this.deleteRemovedFiles(siteId, diffResult.deletedFiles);
    }

    // TODO: Document this limitation / Find a solution to also move files when knowledge base scopeId changes
    // 2. Handle moved files (update scopes)
    if (diffResult.movedFiles.length > 0) {
      await this.fileMoveProcessor.processFileMoves(diffResult.movedFiles, items, scopes, context);
    }

    // 3. Process new/updated files
    const newFileKeys = new Set(diffResult.newFiles);
    const updatedFileKeys = new Set(diffResult.updatedFiles);

    // Check limit only for new/updated files after deletions and moves are processed
    const totalFilesToIngest = newFileKeys.size + updatedFileKeys.size;
    const maxIngestedFiles = this.configService.get('unique.maxIngestedFiles', { infer: true });

    assert.ok(
      !maxIngestedFiles || totalFilesToIngest <= maxIngestedFiles,
      `${logPrefix} Too many files to ingest: ${totalFilesToIngest}. Limit is ${maxIngestedFiles}. Aborting sync.`,
    );

    if (newFileKeys.size === 0 && updatedFileKeys.size === 0) {
      this.logger.log(`${logPrefix} No new/updated files to sync`);
      return;
    }

    const newItems = items.filter((item) => newFileKeys.has(item.item.id));
    const updatedItems = items.filter((item) => updatedFileKeys.has(item.item.id));

    const getScopeIdForItem = (itemId: string): string => {
      const scopeId = context.rootScopeId;

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
      return this.scopeManagementService.determineScopeForItem(item, scopes, context) || scopeId;
    };

    await this.orchestrator.processItems(context, newItems, updatedItems, getScopeIdForItem);

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

    const fileDiffResult = await this.uniqueFileIngestionService.performFileDiff(
      fileDiffItems,
      siteId,
    );

    await this.validateNoAccidentalFullDeletion(fileDiffItems, fileDiffResult, siteId);

    return fileDiffResult;
  }

  private async validateNoAccidentalFullDeletion(
    fileDiffItems: FileDiffItem[],
    fileDiffResult: FileDiffResponse,
    siteId: string,
  ): Promise<void> {
    // If there are no files to be deleted, there's no point in checking further, we will surely not
    // perform full deletion.
    if (fileDiffResult.deletedFiles.length === 0) {
      return;
    }

    const logSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
    const logPrefix = `[Site: ${logSiteId}]`;

    // If the file diff indicated we should delete all files by having submitted no files to the
    // diff, it most probably means that we have some kind of bug in fetching the files from
    // Sharepoint and we should not proceed with the sync to avoid costly re-ingestions. In case
    // user actually wants to delete all files from a site, they should add one dummy file to the
    // site and mark it for synchronization.
    if (fileDiffItems.length === 0) {
      this.logger.error({
        msg:
          `${logPrefix} File diff declares all ${fileDiffResult.deletedFiles.length} files as to ` +
          `be deleted. Aborting sync to prevent accidental full deletion. If you wish to delete ` +
          `all files, add a dummy file to the site and mark it for synchronization.`,
        siteId: logSiteId,
        itemsLength: fileDiffItems.length,
        fileDiffResultCounts: mapValues(fileDiffResult, length()),
      });
      assert.fail(
        `${logPrefix} We submitted 0 files to the file diff and that would result in all ` +
          `${fileDiffResult.deletedFiles.length} files being deleted. Aborting sync to prevent ` +
          `accidental full deletion.`,
      );
    }

    // If the file diff indicated we should delete all files even when we submitted some files to
    // diff, it most probably means that we have some kind of bug in file diff or something
    // unexpected changed in the logic. We should not proceed with the sync to avoid costly
    // re-ingestions. If user actually deleted all the files from the site and uploaded new ones,
    // they should recursively delete the site data from Unique first via GraphQL API.
    const totalFilesForSiteInUnique = await this.uniqueFilesService.getFilesCountForSite(siteId);
    if (fileDiffResult.deletedFiles.length === totalFilesForSiteInUnique) {
      this.logger.error({
        msg:
          `${logPrefix} File diff declares all ${fileDiffResult.deletedFiles.length} files ` +
          `stored in Unique as to be deleted. Aborting sync to prevent accidental full deletion. ` +
          `If you wish to delete all files, add a dummy file to the site and mark it for ` +
          `synchronization.`,
        siteId: logSiteId,
        totalFilesForSiteInUnique,
        fileDiffResultCounts: mapValues(fileDiffResult, length()),
      });
      assert.fail(
        `${logPrefix} File diff declares all ${fileDiffResult.deletedFiles.length} files stored ` +
          `in Unique as to be deleted. Aborting sync to prevent accidental full deletion.`,
      );
    }
  }

  private async deleteRemovedFiles(siteId: string, deletedFileKeys: string[]): Promise<void> {
    const logSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
    const logPrefix = `[Site: ${logSiteId}]`;
    let filesToDelete: UniqueFile[] = [];
    // Convert relative keys to full keys (with siteId prefix)
    const fullKeys = deletedFileKeys.map((key) => `${siteId}/${key}`);

    try {
      // Get content that matches the exact keys
      filesToDelete = await this.uniqueFilesService.getFilesByKeys(fullKeys);
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to get content for deleted files, cannot delete ${deletedFileKeys.length} ingested files`,
        deletedFileKeysCount: deletedFileKeys.length,
        error: sanitizeError(error),
      });
      return;
    }

    // Delete each file
    let totalDeleted = 0;
    for (const file of filesToDelete) {
      try {
        await this.uniqueFilesService.deleteFile(file.id);
        totalDeleted++;

        this.spcFileDeletedTotal.add(1, {
          sp_site_id: logSiteId,
          result: 'success',
        });
      } catch (error) {
        this.spcFileDeletedTotal.add(1, {
          sp_site_id: logSiteId,
          result: 'failure',
        });

        this.logger.error({
          msg: `${logPrefix} Failed to delete content`,
          fileKey: file.key,
          fileId: file.id,
          error: sanitizeError(error),
        });
      }
    }

    this.logger.log(
      `${logPrefix} Completed file deletion in Unique: ${totalDeleted}/${deletedFileKeys.length} files deleted files`,
    );
  }
}
