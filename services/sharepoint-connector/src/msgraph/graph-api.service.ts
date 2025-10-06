import { Client } from '@microsoft/microsoft-graph-client';
import type { Drive, DriveItem } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { Config } from '../config';
import { FileFilterService } from './file-filter.service';
import { GraphClientFactory } from './graph-client.factory';
import type { EnrichedDriveItem } from './types/enriched-drive-item';

@Injectable()
export class GraphApiService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly graphClient: Client;
  private readonly limiter: Bottleneck;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly configService: ConfigService<Config, true>,
    private readonly fileFilterService: FileFilterService,
  ) {
    this.graphClient = this.graphClientFactory.createClient();

    const msGraphRateLimitPer10Seconds = this.configService.get(
      'pipeline.msGraphRateLimitPer10Seconds',
      { infer: true },
    );

    this.limiter = new Bottleneck({
      reservoir: msGraphRateLimitPer10Seconds,
      reservoirRefreshAmount: msGraphRateLimitPer10Seconds,
      reservoirRefreshInterval: 10000,
    });
  }

  public async getAllFilesForSite(siteId: string): Promise<EnrichedDriveItem[]> {
    const maxFilesToScan = this.configService.get('sharepoint.maxFilesToScan', { infer: true });
    const allSyncableFiles: EnrichedDriveItem[] = [];
    let totalScanned = 0;

    if (maxFilesToScan) {
      this.logger.warn(`File scan limit set to ${maxFilesToScan} files for testing purpose.`);
    }

    const [siteWebUrl, drives] = await Promise.all([
      await this.getSiteWebUrl(siteId),
      await this.getDrivesForSite(siteId),
    ]);

    for (const drive of drives) {
      if (!drive.id || !drive.name) continue;

      const remainingLimit = maxFilesToScan ? maxFilesToScan - totalScanned : undefined;
      const filesInDrive = await this.recursivelyFetchFiles(
        drive.id,
        'root',
        siteId,
        siteWebUrl,
        drive.name,
        remainingLimit,
      );

      allSyncableFiles.push(...filesInDrive);
      totalScanned += filesInDrive.length;

      // Stop scanning if we've reached the limit for testing
      if (maxFilesToScan && totalScanned >= maxFilesToScan) {
        this.logger.log(`Reached file scan limit of ${maxFilesToScan}, stopping scan`);
        break;
      }
    }

    this.logger.log(
      `Completed scan for site ${siteId}. Found ${allSyncableFiles.length} files marked for synchronizing.`,
    );
    return allSyncableFiles;
  }

  public async downloadFileContent(driveId: string, itemId: string): Promise<Buffer> {
    this.logger.debug(`Downloading file content for item ${itemId} from drive ${driveId}`);
    const maxFileSizeBytes = this.configService.get('pipeline.maxFileSizeBytes', { infer: true });

    try {
      const stream: ReadableStream = await this.makeRateLimitedRequest(() =>
        this.graphClient.api(`/drives/${driveId}/items/${itemId}/content`).getStream(),
      );

      const chunks: Buffer[] = [];
      let totalSize = 0;

      for await (const chunk of stream) {
        const bufferChunk = Buffer.from(chunk);
        totalSize += bufferChunk.length;

        // This is how we need to cancel the download stream
        if (totalSize > maxFileSizeBytes) {
          const reader = stream.getReader();
          await reader.cancel();
          reader.releaseLock();
          throw new Error(`File size exceeds maximum limit of ${maxFileSizeBytes} bytes.`);
        }

        chunks.push(bufferChunk);
      }
      return Buffer.concat(chunks);
    } catch (error) {
      this.logger.error(`Failed to download file content for item ${itemId}:`, error);
      throw error;
    }
  }

  private async getSiteWebUrl(siteId: string): Promise<string> {
    try {
      const site = await this.makeRateLimitedRequest(() =>
        this.graphClient.api(`/sites/${siteId}`).select('webUrl').get(),
      );

      return site.webUrl;
    } catch (error) {
      this.logger.error(`Failed to fetch site info for ${siteId}:`, error);
      throw error;
    }
  }

  private async getDrivesForSite(siteId: string): Promise<Drive[]> {
    try {
      const drives = await this.makeRateLimitedRequest(() =>
        this.graphClient.api(`/sites/${siteId}/drives`).get(),
      );

      const allDrives = drives?.value || [];
      this.logger.log(`Found ${allDrives.length} drives for site ${siteId}`);

      return allDrives;
    } catch (error) {
      this.logger.error(`Failed to fetch drives for site ${siteId}:`, error);
      throw error;
    }
  }

  private async recursivelyFetchFiles(
    driveId: string,
    itemId: string,
    siteId: string,
    siteWebUrl: string,
    driveName: string,
    maxFiles?: number,
  ): Promise<EnrichedDriveItem[]> {
    try {
      const allItems = await this.fetchAllItemsInFolder(driveId, itemId);
      const filesToSynchronize: EnrichedDriveItem[] = [];

      for (const driveItem of allItems) {
        // Check if we've reached the file limit for local testing
        if (maxFiles && filesToSynchronize.length >= maxFiles) {
          this.logger.warn(`Reached file limit of ${maxFiles}, stopping scan in ${itemId}`);
          break;
        }

        if (this.isFolder(driveItem)) {
          const remainingLimit = maxFiles ? maxFiles - filesToSynchronize.length : undefined;
          const filesInSubfolder = await this.recursivelyFetchFiles(
            driveId,
            driveItem.id,
            siteId,
            siteWebUrl,
            driveName,
            remainingLimit,
          );

          filesToSynchronize.push(...filesInSubfolder);
        } else if (this.fileFilterService.isFileValidForIngestion(driveItem)) {
          const folderPath = this.extractFolderPath(driveItem);
          filesToSynchronize.push({
            ...driveItem,
            siteId,
            siteWebUrl,
            driveId,
            driveName,
            folderPath,
          });
        }
      }

      return filesToSynchronize;
    } catch (error) {
      this.logger.error(`Failed to fetch items for drive ${driveId}, item ${itemId}:`, error);
      // TODO: Look if it's worth adding a retry mechanism - also check implications with file-diffing
    }
  }

  //Example path: /drives/b!abc123def456/root:/Documents/Projects ; Removes root: from the folder path
  private extractFolderPath(driveItem: DriveItem): string {
    if (!driveItem.parentReference?.path) {
      return '';
    }

    const fullPath = driveItem.parentReference.path;
    const rootPattern = /^\/drives\/[^/]+\/root:?/;
    const cleanPath = fullPath.replace(rootPattern, '');

    return cleanPath || '/';
  }

  private async fetchAllItemsInFolder(driveId: string, itemId: string): Promise<DriveItem[]> {
    const itemsInFolder: DriveItem[] = [];
    const selectFields = [
      'id',
      'name',
      'webUrl',
      'size',
      'lastModifiedDateTime',
      'folder',
      'file',
      'listItem',
      'parentReference',
    ];
    let nextPageUrl = `/drives/${driveId}/items/${itemId}/children`;

    while (nextPageUrl) {
      const response = await this.makeRateLimitedRequest(() =>
        this.graphClient
          .api(nextPageUrl)
          .select(selectFields)
          .expand('listItem($expand=fields)')
          .get(),
      );

      const items: DriveItem[] = response?.value || [];
      itemsInFolder.push(...items);

      nextPageUrl = response['@odata.nextLink'] || '';
    }

    return itemsInFolder;
  }

  private async makeRateLimitedRequest<T>(requestFn: () => Promise<T>): Promise<T> {
    return await this.limiter.schedule(async () => await requestFn());
  }

  private isFolder(driveItem: DriveItem): driveItem is DriveItem & { id: string } {
    return Boolean(driveItem.folder && driveItem.id);
  }
}
