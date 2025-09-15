import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { UniqueAuthService } from '../auth/unique-auth.service';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { SharepointApiService } from '../sharepoint-api/sharepoint-api.service';
import type { FileDiffItem } from '../unique-api/types/unique-api.types';
import { UniqueApiService } from '../unique-api/unique-api.service';

@Injectable()
export class SharepointScannerService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService,
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly sharepointApiService: SharepointApiService,
    private readonly orchestrator: FileProcessingOrchestratorService,
    private readonly uniqueApiService: UniqueApiService,
  ) {}

  public async scanForWork(): Promise<void> {
    const scanStartTime = Date.now();
    const sitesToScan = this.configService.get<string[]>('sharepoint.sites');
    if (!sitesToScan || sitesToScan.length === 0) {
      this.logger.warn(
        'No SharePoint sites configured for scanning. Please check your configuration.',
      );
      return;
    }

    try {
      this.logger.log(`Starting scan of ${sitesToScan.length} SharePoint sites...`);
      for (const siteId of sitesToScan) {
        try {
          const files = await this.sharepointApiService.findAllSyncableFilesForSite(siteId);
          this.logger.debug(`Found ${files.length} syncable files in site ${siteId}`);
          if (!files.length) {
            continue;
          }
          const fileDiffItems: FileDiffItem[] = files.map((file) => ({
            id: file.id,
            name: file.name,
            url: file.webUrl,
            updatedAt: file.listItem.lastModifiedDateTime,
            key: `sharepoint_file_${file.id}`,
          }));
          const uniqueToken = await this.uniqueAuthService.getToken();
          const diffResult = await this.uniqueApiService.performFileDiff(
            fileDiffItems,
            uniqueToken,
          );
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
      const _scanDurationSeconds = (Date.now() - scanStartTime) / 1000;
    } catch (error) {
      this.logger.error(
        'Failed to complete SharePoint scan:',
        error instanceof Error ? error.stack : String(error),
      );
    }
  }
}
