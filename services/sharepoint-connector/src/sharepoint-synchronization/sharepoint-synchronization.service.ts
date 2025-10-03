import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { GraphApiService } from '../msgraph/graph-api.service';
import type { EnrichedDriveItem } from '../msgraph/types/enriched-drive-item';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import { buildSharepointFileKey, buildSharepointPartialKey } from '../shared/sharepoint-key.util';
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
    const sitesToScan = this.configService.get('sharepoint.sites', { infer: true });

    this.logger.log(`Starting scan of ${sitesToScan.length} SharePoint sites...`);

    for (const siteId of sitesToScan) {
      try {
        const files = await this.graphApiService.getAllFilesForSite(siteId);
        if (files.length === 0) {
          continue;
        }
        // check what happens if a siteid is empty?
        // if no files are in a site we still need to send the request to diff-file endpoint

        const diffResult = await this.calculateDiffForFiles(files);
        this.logger.log(
          `Site ${siteId}: ${diffResult.newAndUpdatedFiles.length} files need processing, ${diffResult.deletedFiles.length} deleted`,
        );

        await this.orchestrator.processFilesForSite(siteId, files, diffResult);
      } catch (error) {
        this.logger.error(
          `Failed during processing of site ${siteId}:`,
          error instanceof Error ? error.stack : String(error),
        );
      }
    }

    const scanDurationSeconds = (Date.now() - scanStartTime) / 1000;
    this.logger.log(`SharePoint scan completed in ${scanDurationSeconds.toFixed(2)}s`);
    this.isScanning = false;
  }

  /*
    This step also triggers file deletion in node-ingestion service when a file is missing.
   */
  private async calculateDiffForFiles(files: EnrichedDriveItem[]): Promise<FileDiffResponse> {
    const scopeId = this.configService.get('uniqueApi.scopeId', { infer: true });

    const fileDiffItems: FileDiffItem[] = files.map((file: EnrichedDriveItem) => ({
      id: file.id,
      name: file.name,
      url: file.webUrl,
      updatedAt: file.listItem?.lastModifiedDateTime,
      key: buildSharepointFileKey({
        scopeId,
        siteId: file.siteId,
        driveName: file.driveName,
        folderPath: file.folderPath,
        fileId: file.id,
        fileName: file.name,
      }),
      driveId: file.driveId,
      siteId: file.siteId,
    }));

    const uniqueToken = await this.uniqueAuthService.getToken();
    const partialKey = buildSharepointPartialKey({ scopeId, siteId: files[0]?.siteId ?? '' });
    return await this.uniqueApiService.performFileDiff(fileDiffItems, uniqueToken, partialKey);
  }
}
