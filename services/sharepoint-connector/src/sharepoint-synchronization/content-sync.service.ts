import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import type { FileDiffItem, FileDiffResponse } from '../unique-api/unique-api.types';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { buildFileDiffKey, getItemUrl } from '../utils/sharepoint.util';
import { elapsedSecondsLog } from '../utils/timing.util';

@Injectable()
export class ContentSyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly orchestrator: FileProcessingOrchestratorService,
    private readonly uniqueApiService: UniqueApiService,
    private readonly configService: ConfigService<Config>,
  ) {}

  public async syncContentForSite(siteId: string, items: SharepointContentItem[]): Promise<void> {
    const logPrefix = `[SiteId: ${siteId}] `;
    const diffResult = await this.calculateDiffForSite(items, siteId);
    this.logger.log(
      `${logPrefix} File Diff Results: ${diffResult.newAndUpdatedFiles.length} files need processing, ${diffResult.deletedFiles.length} deleted`,
    );

    const processStartTime = Date.now();
    await this.orchestrator.processSiteItems(siteId, items, diffResult);

    this.logger.log(
      `${logPrefix} Finished processing content in ${elapsedSecondsLog(processStartTime)}`,
    );
  }

  /*
   This step also triggers file deletion in node-ingestion service when a file is missing.
  */
  private async calculateDiffForSite(
    sharepointContentItems: SharepointContentItem[],
    siteId: string,
  ): Promise<FileDiffResponse> {
    const rootScopeName = this.configService.get('unique.rootScopeName', { infer: true });

    const fileDiffItems: FileDiffItem[] = sharepointContentItems.map(
      (sharepointContentItem: SharepointContentItem) => {
        const key = buildFileDiffKey(sharepointContentItem);

        return {
          key,
          url: getItemUrl(sharepointContentItem, rootScopeName),
          updatedAt: sharepointContentItem.item.lastModifiedDateTime,
        };
      },
    );

    const uniqueToken = await this.uniqueAuthService.getToken();
    return await this.uniqueApiService.performFileDiff(fileDiffItems, uniqueToken, siteId);
  }
}
