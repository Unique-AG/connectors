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

      for (const siteId of sitesToScan) {
        try {
          const files = await this.graphApiService.findAllSyncableFilesForSite(siteId);
          this.logger.log(`Found ${files.length} syncable files in site ${siteId}`);

          if (files.length === 0) {
            continue;
          }

          await this.processSiteFiles(siteId, files);
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
    } finally {
      this.isScanning = false;
    }
  }

  private groupFilesByDrive(files: DriveItem[]): Record<string, DriveItem[]> {
    const grouped: Record<string, DriveItem[]> = {};

    for (const file of files) {
      const parentRef = file.parentReference as Record<string, unknown> | undefined;
      const driveId = (parentRef?.driveId as string | undefined) ?? 'unknown-drive';

      if (!grouped[driveId]) {
        grouped[driveId] = [];
      }
      grouped[driveId].push(file);
    }

    return grouped;
  }

  private async processSiteFiles(siteId: string, files: DriveItem[]): Promise<void> {
    // Group files by drive within this site and process them by drive
    const filesByDrive = this.groupFilesByDrive(files);

    for (const [driveId, driveFiles] of Object.entries(filesByDrive)) {
      this.logger.debug(`Processing ${driveFiles.length} files for drive: ${driveId}`);

      const diffResult = await this.calculateDiffForDrive(driveFiles, siteId, driveId);
      this.logger.debug(
        `Drive ${driveId}: ${diffResult.newAndUpdatedFiles.length} files need processing, ${diffResult.deletedFiles.length} deleted`,
      );

      await this.processFilesForDrive(driveId, driveFiles, diffResult);
    }
  }

  private async processFilesForDrive(
    driveId: string,
    files: DriveItem[],
    diffResult: FileDiffResponse,
  ): Promise<void> {
    const newFileKeys = new Set(diffResult.newAndUpdatedFiles);
    const filesToProcess = files.filter((file) => {
      const key = this.sharePointPathService.generatePathBasedKey(file);
      return newFileKeys.has(key);
    });

    if (filesToProcess.length === 0) {
      this.logger.debug(`No files need processing for drive: ${driveId}`);
      return;
    }

    this.logger.log(`Processing ${filesToProcess.length} files for drive: ${driveId}`);

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
      this.logger.warn(`Drive ${driveId}: Completed processing with ${rejected.length} failures`);
    }
  }

  private async calculateDiffForDrive(
    files: DriveItem[],
    siteId: string,
    driveId: string,
  ): Promise<FileDiffResponse> {
    const fileDiffItems: FileDiffItem[] = files.map((file: DriveItem) => ({
      id: file.id,
      name: file.name,
      url: file.webUrl,
      updatedAt: file.listItem?.lastModifiedDateTime,
      key: this.sharePointPathService.generatePathBasedKey(file),
    }));

    const uniqueToken = await this.uniqueAuthService.getToken();
    const diffResult = await this.uniqueApiService.performFileDiff(fileDiffItems, uniqueToken, siteId, driveId);

    return diffResult;
  }
}
