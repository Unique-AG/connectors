import { Client } from '@microsoft/microsoft-graph-client';
import type { Drive, DriveItem } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { FileFilterService } from './file-filter.service';
import { GraphClientFactory } from './graph-client.factory';

@Injectable()
export class GraphApiService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly graphClient: Client;
  private readonly limiter: Bottleneck;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly configService: ConfigService,
    private readonly fileFilterService: FileFilterService,
  ) {
    this.graphClient = this.graphClientFactory.createClient();

    const msGraphRateLimitPer10Seconds = this.configService.get<number>(
      'pipeline.msGraphRateLimitPer10Seconds',
      10000,
    );

    this.limiter = new Bottleneck({
      reservoir: msGraphRateLimitPer10Seconds,
      reservoirRefreshAmount: msGraphRateLimitPer10Seconds,
      reservoirRefreshInterval: 10000,
    });
  }

  public async findAllSyncableFilesForSite(siteId: string): Promise<DriveItem[]> {
    this.logger.log(`Starting recursive file scan for site: ${siteId}`);

    const site = await this.getSite(siteId);
    const drives = await this.getDrivesForSite(siteId);
    const allSyncableFiles: DriveItem[] = [];

    for (const drive of drives) {
      if (!drive.id) {
        this.logger.warn(`Drive ${drive.name} has no ID, skipping`);
        continue;
      }

      this.logger.debug(`Scanning library (drive): ${drive.name} (${drive.id})`);
      const filesInDrive = await this.recursivelyFetchSyncableFiles(drive.id, 'root');
      
      const enrichedFiles = filesInDrive.map((file) => ({
        ...file,
        parentReference: {
          ...file.parentReference,
          name: drive.name,
          siteName: site?.displayName ?? site?.name ?? siteId,
        },
      }));
      
      allSyncableFiles.push(...enrichedFiles);
    }

    this.logger.log(
      `Completed scan for site ${siteId}. Found ${allSyncableFiles.length} syncable files.`,
    );
    return allSyncableFiles;
  }

  public async downloadFileContent(driveId: string, itemId: string): Promise<Buffer> {
    this.logger.debug(`Downloading file content for item ${itemId} from drive ${driveId}`);
    const maxFileSizeBytes = this.configService.get<number>('pipeline.maxFileSizeBytes') as number;

    try {
      const stream: ReadableStream = await this.makeRateLimitedRequest(() =>
        this.graphClient.api(`/drives/${driveId}/items/${itemId}/content`).getStream(),
      );

      const chunks: Buffer[] = [];
      let totalSize = 0;

      for await (const chunk of stream) {
        const bufferChunk = Buffer.from(chunk);
        totalSize += bufferChunk.length;

        if (totalSize > maxFileSizeBytes) {
          const reader = stream.getReader();
          await reader.cancel();
          reader.releaseLock();
          throw new Error(`File size exceeds maximum limit of ${maxFileSizeBytes} bytes.`);
        }

        chunks.push(bufferChunk);
      }

      this.logger.log(`File download completed. Total size: ${totalSize} bytes.`);
      return Buffer.concat(chunks);
    } catch (error) {
      this.logger.error(`Failed to download file content for item ${itemId}:`, error);
      throw error;
    }
  }

  private async getSite(siteId: string): Promise<{ displayName?: string; name?: string } | null> {
    try {
      this.logger.debug(`Fetching site details: ${siteId}`);

      const site = await this.makeRateLimitedRequest(() =>
        this.graphClient.api(`/sites/${siteId}`).select(['displayName', 'name']).get(),
      );

      return site as { displayName?: string; name?: string };
    } catch (error) {
      this.logger.warn(`Failed to fetch site details for ${siteId}:`, error);
      return null;
    }
  }

  private async getDrivesForSite(siteId: string): Promise<Drive[]> {
    try {
      this.logger.debug(`Fetching drives for site: ${siteId}`);

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

  private async recursivelyFetchSyncableFiles(
    driveId: string,
    itemId: string,
  ): Promise<DriveItem[]> {
    try {
      this.logger.debug(`Fetching items for drive ${driveId}, item ${itemId}`);

      const allItems = await this.fetchAllItemsInFolder(driveId, itemId);
      const syncableFiles: DriveItem[] = [];

      for (const driveItem of allItems) {
        if (this.isFolder(driveItem)) {
          const filesInSubfolder = await this.recursivelyFetchSyncableFiles(driveId, driveItem.id);
          syncableFiles.push(...filesInSubfolder);
        } else if (this.isFile(driveItem)) {
          if (this.fileFilterService.isFileSyncable(driveItem)) {
            syncableFiles.push(driveItem);
          }
        }
      }

      syncableFiles.length !== 0 && this.logger.log(
        `Found ${syncableFiles.length} syncable files in drive ${driveId}, item ${itemId}`,
      );
      return syncableFiles;
    } catch (error) {
      this.logger.error(`Failed to fetch items for drive ${driveId}, item ${itemId}:`, error);
      throw error;
    }
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

  private isFile(driveItem: DriveItem): boolean {
    return Boolean(driveItem.file);
  }
}
