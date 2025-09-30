import type { DriveItem } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import pLimit from 'p-limit';
import { UniqueAuthService } from '../auth/unique-auth.service';
import { GraphApiService } from '../msgraph/graph-api.service';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import type { FileDiffItem, FileDiffResponse } from '../unique-api/unique-api.types';
import { SharePointPathService } from '../utils/sharepoint-path.service';

@Injectable()
export class SharepointSynchronizationService {
  private readonly logger = new Logger(this.constructor.name);
  private isScanning = false;

  public constructor(
    private readonly configService: ConfigService,
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly graphApiService: GraphApiService,
    private readonly orchestrator: FileProcessingOrchestratorService,
    private readonly uniqueApiService: UniqueApiService,
    private readonly sharePointPathService: SharePointPathService,
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

    try {
      const sitesToScan = this.configService.get<string[]>('sharepoint.sites') as string[];
      this.logger.log(`Starting scan of ${sitesToScan.length} SharePoint sites...`);

      const allFiles: DriveItem[] = [];

      for (const siteId of sitesToScan) {
        try {
          const files = await this.graphApiService.findAllSyncableFilesForSite(siteId);
          this.logger.log(`Found ${files.length} syncable files in site ${siteId}`);
          allFiles.push(...files);
        } catch (error) {
          this.logger.error(
            `Failed to scan site ${siteId}:`,
            error instanceof Error ? error.stack : String(error),
          );
        }
      }

      if (allFiles.length === 0) {
        this.logger.log('No syncable files found across all sites');
        return;
      }

      this.logger.log(`Total files found across all sites: ${allFiles.length}`);

      // Group files by site for separate ingestion directories
      const filesBySite = this.groupFilesBySite(allFiles);

      for (const [siteName, siteFiles] of Object.entries(filesBySite)) {
        this.logger.debug(`Processing ${siteFiles.length} files for site: ${siteName}`);

        const diffResult = await this.calculateDiffForSite(siteFiles, siteName);
        this.logger.debug(
          `Site ${siteName}: ${diffResult.newAndUpdatedFiles.length} files need processing, ${diffResult.deletedFiles.length} deleted`,
        );

        await this.processFilesForSite(siteName, siteFiles, diffResult);
      }

      const scanDurationSeconds = (Date.now() - scanStartTime) / 1000;
      this.logger.log(`SharePoint scan completed in ${scanDurationSeconds.toFixed(2)}s`);
    } catch (error) {
      this.logger.error(
        'Failed to complete SharePoint scan:',
        error instanceof Error ? error.stack : String(error),
      );
    } finally {
      this.isScanning = false;
    }
  }

  private groupFilesBySite(files: DriveItem[]): Record<string, DriveItem[]> {
    const grouped: Record<string, DriveItem[]> = {};

    for (const file of files) {
      const parentRef = file.parentReference as Record<string, unknown> | undefined;
      const siteName = (parentRef?.siteName as string | undefined) ?? 'unknown-site';

      if (!grouped[siteName]) {
        grouped[siteName] = [];
      }
      grouped[siteName].push(file);
    }

    return grouped;
  }

  private async processFilesForSite(
    siteName: string,
    files: DriveItem[],
    diffResult: FileDiffResponse,
  ): Promise<void> {
    const newFileKeys = new Set(diffResult.newAndUpdatedFiles);
    const filesToProcess = files.filter((file) => {
      const key = this.sharePointPathService.generatePathBasedKey(file);
      return newFileKeys.has(key);
    });

    if (filesToProcess.length === 0) {
      this.logger.debug(`No files need processing for site: ${siteName}`);
      return;
    }

    this.logger.log(`Processing ${filesToProcess.length} files for site: ${siteName}`);

    const concurrency = this.configService.get<number>('pipeline.processingConcurrency') as number;
    const limit = pLimit(concurrency);

    const processFile = async (file: DriveItem) => {
      const siteId = file.parentReference?.siteId ?? '';
      const fileKey = this.sharePointPathService.generatePathBasedKey(file);

      return this.orchestrator.processFilesForSite(siteId, [file], {
        newAndUpdatedFiles: [fileKey],
        deletedFiles: [],
        movedFiles: [],
      });
    };

    const results = await Promise.allSettled(
      filesToProcess.map((file) => limit(() => processFile(file))),
    );

    const rejected = results.filter((r) => r.status === 'rejected');
    if (rejected.length > 0) {
      this.logger.warn(`Site ${siteName}: Completed processing with ${rejected.length} failures`);
    }
  }


  private async calculateDiffForSite(files: DriveItem[], siteName: string): Promise<FileDiffResponse> {
    const fileDiffItems: FileDiffItem[] = files.map((file: DriveItem) => ({
      id: file.id,
      name: file.name,
      url: file.webUrl,
      updatedAt: file.listItem?.lastModifiedDateTime,
      key: this.sharePointPathService.generatePathBasedKey(file),
    }));

    const uniqueToken = await this.uniqueAuthService.getToken();
    const diffResult = await this.uniqueApiService.performFileDiff(fileDiffItems, uniqueToken, siteName);

    return diffResult;
  }
}
