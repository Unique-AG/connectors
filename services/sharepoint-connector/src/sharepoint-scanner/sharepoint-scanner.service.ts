import type { DriveItem } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { UniqueAuthService } from '../auth/unique-auth.service';
import { GraphApiService } from '../msgraph/graph-api.service';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import type { FileDiffItem, FileDiffResponse } from '../unique-api/unique-api.types';

@Injectable()
export class SharepointScannerService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService,
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly graphApiService: GraphApiService,
    private readonly orchestrator: FileProcessingOrchestratorService,
    private readonly uniqueApiService: UniqueApiService,
  ) {}

  public async runSync(): Promise<void> {
    const scanStartTime = Date.now();
    const sitesToScan = this.configService.get<string[]>('sharepoint.sites') as string[];

    if (sitesToScan.length === 0) {
      this.logger.warn(
        'No SharePoint sites configured for scanning. Please check your configuration.',
      );
      return;
    }

    try {
      this.logger.log(`Starting scan of ${sitesToScan.length} SharePoint sites...`);

      for (const siteId of sitesToScan) {
        try {
          const files = await this.graphApiService.findAllSyncableFilesForSite(siteId);
          this.logger.log(`Found ${files.length} syncable files in site ${siteId}`);

          if (files.length === 0) {
            continue;
          }

          const diffResult = await this.calculateDiffForFiles(files);
          this.logger.debug(
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
    } catch (error) {
      this.logger.error(
        'Failed to complete SharePoint scan:',
        error instanceof Error ? error.stack : String(error),
      );
    }
  }

  private async calculateDiffForFiles(files: DriveItem[]): Promise<FileDiffResponse> {
    const fileDiffItems: FileDiffItem[] = files.map((file: DriveItem) => ({
      id: file.id,
      name: file.name,
      url: file.webUrl,
      updatedAt: file.listItem?.lastModifiedDateTime,
      key: `sharepoint_file_${file.id}`,
    }));

    const uniqueToken = await this.uniqueAuthService.getToken();
    const diffResult = await this.uniqueApiService.performFileDiff(fileDiffItems, uniqueToken);

    return diffResult;
  }
}
