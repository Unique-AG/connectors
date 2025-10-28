import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import type { FileDiffItem, FileDiffResponse } from '../unique-api/unique-api.types';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { normalizeError } from '../utils/normalize-error';
import { getItemUrl } from '../utils/sharepoint.util';

@Injectable()
export class SharepointSynchronizationService {
  private readonly logger = new Logger(this.constructor.name);
  private isScanning = false;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly graphApiService: GraphApiService,
    private readonly orchestrator: FileProcessingOrchestratorService,
    private readonly uniqueApiService: UniqueApiService,
  ) {}

  public async synchronize(): Promise<void> {
    if (this.isScanning) {
      this.logger.warn(
        'Skipping scan - previous scan is still in progress. This prevents overlapping scans.',
      );
      return;
    }
    this.isScanning = true;
    const scanStartTime = Date.now();
    const siteIdsToScan = this.configService.get('sharepoint.siteIds', { infer: true });

    this.logger.log(`Starting scan of ${siteIdsToScan.length} SharePoint sites...`);

    for (const siteId of siteIdsToScan) {
      const siteStartTime = Date.now();
      try {
        const items = await this.graphApiService.getAllSiteItems(siteId);

        this.logger.log(
          `Finished scanning site id ${siteId} in ${((Date.now() - siteStartTime) / 1000).toFixed(2)} seconds`,
        );

        const diffResult = await this.calculateDiffForSite(items, siteId);
        this.logger.log(
          `File Diff Results: Site ${siteId}: ${diffResult.newAndUpdatedFiles.length} files need processing, ${diffResult.deletedFiles.length} deleted`,
        );

        const processStartTime = Date.now();
        await this.orchestrator.processSiteItems(siteId, items, diffResult);

        this.logger.log(
          `Finished processing site ${siteId} in ${((Date.now() - processStartTime) / 1000).toFixed(2)} seconds`,
        );
      } catch (rawError) {
        const error = normalizeError(rawError);
        this.logger.error({
          msg: `Failed during processing of site ${siteId}: ${error.message}`,
          err: rawError,
        });
      }
    }

    const scanDurationSeconds = (Date.now() - scanStartTime) / 1000;
    this.logger.log(
      `SharePoint scan finished scanning all sites in ${scanDurationSeconds.toFixed(2)}s`,
    );
    this.isScanning = false;
  }

  /*
    This step also triggers file deletion in node-ingestion service when a file is missing.
   */
  private async calculateDiffForSite(
    sharepointContentItems: SharepointContentItem[],
    siteId: string,
  ): Promise<FileDiffResponse> {
    const fileDiffItems: FileDiffItem[] = sharepointContentItems.map(
      (sharepointContentItem: SharepointContentItem) => {
        return {
          key: sharepointContentItem.item.id,
          url: getItemUrl(sharepointContentItem),
          updatedAt: sharepointContentItem.item.lastModifiedDateTime,
        };
      },
    );

    const uniqueToken = await this.uniqueAuthService.getToken();
    return await this.uniqueApiService.performFileDiff(fileDiffItems, uniqueToken, siteId);
  }
}
