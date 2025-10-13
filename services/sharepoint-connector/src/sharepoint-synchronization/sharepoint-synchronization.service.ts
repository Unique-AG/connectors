import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { normalizeError } from '../utils/normalize-error';
import { Config } from '../config';
import { GraphApiService } from '../msgraph/graph-api.service';
import type { EnrichedDriveItem } from '../msgraph/types/enriched-drive-item';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { buildSharepointPartialKey } from '../shared/sharepoint-key.util';
import { buildKnowledgeBaseUrl } from '../shared/sharepoint-url.util';
import { UniqueApiService } from '../unique-api/unique-api.service';
import type { FileDiffItem, FileDiffResponse } from '../unique-api/unique-api.types';
import { UniqueAuthService } from '../unique-api/unique-auth.service';

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
      try {
        const files = await this.graphApiService.getAllFilesForSite(siteId);
        const diffResult = await this.calculateDiffForFiles(files, siteId);
        this.logger.log(
          `File Diff Result: Site ${siteId}: ${diffResult.newAndUpdatedFiles.length} files need processing, ${diffResult.deletedFiles.length} deleted`,
        );

        await this.orchestrator.processFilesForSite(siteId, files, diffResult);

        const siteScanDurationSeconds = (Date.now() - scanStartTime) / 1000;
        this.logger.log(`Finished processing site ${siteId} in ${siteScanDurationSeconds.toFixed(2)}s`);
      } catch (rawError) {
        const error = normalizeError(rawError);
        this.logger.error({
          msg: `Failed during processing of site ${siteId}: ${error.message}`,
          err: rawError,
        });
      }
    }

    const scanDurationSeconds = (Date.now() - scanStartTime) / 1000;
    this.logger.log(`SharePoint scan finished scanning all sites in ${scanDurationSeconds.toFixed(2)}s`);
    this.isScanning = false;
  }

  /*
    This step also triggers file deletion in node-ingestion service when a file is missing.
   */
  private async calculateDiffForFiles(
    files: EnrichedDriveItem[],
    siteId: string,
  ): Promise<FileDiffResponse> {
    const scopeId = this.configService.get('unique.scopeId', { infer: true });

    const fileDiffItems: FileDiffItem[] = files.map((file: EnrichedDriveItem) => {
      return {
        key: file.name, // It is a must to send just the filename
        url: buildKnowledgeBaseUrl(file), // SharePoint URL for location
        updatedAt: file.listItem?.lastModifiedDateTime as string,
      };
    });

    const uniqueToken = await this.uniqueAuthService.getToken();
    const partialKey = buildSharepointPartialKey({ scopeId, siteId });
    return await this.uniqueApiService.performFileDiff(fileDiffItems, uniqueToken, partialKey);
  }
}
