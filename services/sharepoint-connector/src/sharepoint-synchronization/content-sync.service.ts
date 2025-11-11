import { Injectable, Logger } from '@nestjs/common';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { UniqueFileIngestionService } from '../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import type {
  FileDiffItem,
  FileDiffResponse,
} from '../unique-api/unique-file-ingestion/unique-file-ingestion.types';
import { ItemProcessingOrchestratorService } from '../processing-pipeline/item-processing-orchestrator.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { buildFileDiffKey, getItemUrl } from '../utils/sharepoint.util';
import { elapsedSecondsLog } from '../utils/timing.util';
import type { ScopePathToIdMap } from './scope-management.service';

@Injectable()
export class ContentSyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly orchestrator: FileProcessingOrchestratorService,
    private readonly uniqueFileIngestionService: UniqueFileIngestionService,
  ) {}

  public async syncContentForSite(
    siteId: string,
    items: SharepointContentItem[],
    scopePathToIdMap?: ScopePathToIdMap,
    itemIdToScopePathMap?: Map<string, string>,
  ): Promise<void> {
    const logPrefix = `[SiteId: ${siteId}] `;
    const processStartTime = Date.now();

    const diffResult = await this.calculateDiffForSite(items, siteId);

    this.logger.log(
      `${logPrefix} File Diff Results: ${diffResult.newFiles.length} new, ${diffResult.updatedFiles.length} updated, ${diffResult.movedFiles.length} moved, ${diffResult.deletedFiles.length} deleted`,
    );

    const fileKeysToSync = new Set([...diffResult.newFiles, ...diffResult.updatedFiles]);
    if (fileKeysToSync.size === 0) {
      this.logger.log(`${logPrefix} No files to sync`);
      return;
    }

    const itemsToSync = items.filter((item) => fileKeysToSync.has(item.item.id));

    await this.orchestrator.processSiteItems(
      siteId,
      itemsToSync,
      scopePathToIdMap,
      itemIdToScopePathMap,
    );

    this.logger.log(
      `${logPrefix} Finished processing content in ${elapsedSecondsLog(processStartTime)}`,
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
}
