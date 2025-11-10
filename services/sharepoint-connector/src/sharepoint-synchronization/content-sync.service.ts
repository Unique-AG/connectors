import { Injectable, Logger } from '@nestjs/common';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { ItemProcessingOrchestratorService } from '../processing-pipeline/item-processing-orchestrator.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import type { FileDiffItem, FileDiffResponse } from '../unique-api/unique-api.types';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { buildFileDiffKey, getItemUrl } from '../utils/sharepoint.util';
import { elapsedSecondsLog } from '../utils/timing.util';
import type { ScopePathToIdMap } from './scope-management.service';

@Injectable()
export class ContentSyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly orchestrator: ItemProcessingOrchestratorService,
    private readonly uniqueApiService: UniqueApiService,
  ) {}

  public async syncContentForSite(
    siteId: string,
    items: SharepointContentItem[],
    scopePathToIdMap?: ScopePathToIdMap,
  ): Promise<void> {
    const logPrefix = `[SiteId: ${siteId}] `;
    const processStartTime = Date.now();

    const diffResult = await this.calculateDiffForSite(items, siteId);

    this.logger.log(
      `${logPrefix} File Diff Results: ${diffResult.newFiles.length} new, ${diffResult.updatedFiles.length} updated, ${diffResult.movedFiles.length} moved, ${diffResult.deletedFiles.length} deleted`,
    );

    const fileKeysToSync = new Set([...diffResult.newFiles, ...diffResult.updatedFiles]);
    const itemsToSync = items.filter((item) => fileKeysToSync.has(item.item.id));

    await this.orchestrator.processItems(siteId, itemsToSync, scopePathToIdMap);

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

    const uniqueToken = await this.uniqueAuthService.getToken();
    return await this.uniqueApiService.performFileDiff(fileDiffItems, uniqueToken, siteId);
  }
}
