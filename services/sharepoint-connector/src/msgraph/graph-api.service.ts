import assert from 'node:assert';
import { Client } from '@microsoft/microsoft-graph-client';
import type { Drive, List } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { Config } from '../config';
import { GRAPH_API_PAGE_SIZE } from '../constants/defaults.constants';
import { getTitle } from '../utils/list-item.util';
import { normalizeError } from '../utils/normalize-error';
import { FileFilterService } from './file-filter.service';
import { GraphClientFactory } from './graph-client.factory';
import {
  DriveItem,
  GraphApiResponse,
  ListItem,
  ListItemDetailsResponse,
  SitePageContent,
} from './types/sharepoint.types';
import { SharepointContentItem } from './types/sharepoint-content-item.interface';

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

    const msGraphRateLimitPerMinute = this.configService.get(
      'sharepoint.graphApiRateLimitPerMinute',
      { infer: true },
    );

    this.limiter = new Bottleneck({
      reservoir: msGraphRateLimitPerMinute,
      reservoirRefreshAmount: msGraphRateLimitPerMinute,
      reservoirRefreshInterval: 60000,
    });
  }

  public async getAllSiteItems(siteId: string): Promise<SharepointContentItem[]> {
    const logPrefix = `[SiteId: ${siteId}] `;
    const [aspxPagesResult, filesResult] = await Promise.allSettled([
      this.getAspxPagesForSite(siteId),
      this.getAllFilesForSite(siteId),
    ]);

    const sharepointContentItemsToSync: SharepointContentItem[] = [];

    if (aspxPagesResult.status === 'fulfilled') {
      sharepointContentItemsToSync.push(...aspxPagesResult.value);
    } else {
      this.logger.error(`${logPrefix} Failed to scan pages:`, aspxPagesResult.reason);
    }

    if (filesResult.status === 'fulfilled') {
      sharepointContentItemsToSync.push(...filesResult.value);
    } else {
      this.logger.error(`${logPrefix} Failed to scan drive files:`, filesResult.reason);
    }

    this.logger.log(
      `${logPrefix} Completed scan. Found ${sharepointContentItemsToSync.length} total items marked for synchronization.`,
    );
    return sharepointContentItemsToSync;
  }

  public async getAllFilesForSite(siteId: string): Promise<SharepointContentItem[]> {
    const maxFilesToScan = this.configService.get('processing.maxFilesToScan', { infer: true });
    const sharepointContentFilesToSync: SharepointContentItem[] = [];
    let totalScanned = 0;

    if (maxFilesToScan) {
      this.logger.warn(`File scan limit set to ${maxFilesToScan} files for testing purpose.`);
    }

    const [siteWebUrl, drives] = await Promise.all([
      this.getSiteWebUrl(siteId),
      this.getDrivesForSite(siteId),
    ]);

    for (const drive of drives) {
      if (!drive.id || !drive.name) continue;

      const remainingLimit = maxFilesToScan ? maxFilesToScan - totalScanned : undefined;
      if (remainingLimit !== undefined && remainingLimit <= 0) {
        this.logger.log(`Reached file scan limit of ${maxFilesToScan}, stopping drive scan`);
        break;
      }

      const filesInDrive = await this.recursivelyFetchDriveItems(
        drive.id,
        'root',
        siteId,
        siteWebUrl,
        drive.name,
        remainingLimit,
      );

      sharepointContentFilesToSync.push(...filesInDrive);
      totalScanned += filesInDrive.length;

      // Stop scanning if we've reached the limit for testing
      if (maxFilesToScan && totalScanned >= maxFilesToScan) {
        this.logger.log(`Reached file scan limit of ${maxFilesToScan}, stopping scan`);
        break;
      }
    }

    this.logger.log(`Found ${sharepointContentFilesToSync.length} drive files for site ${siteId}`);
    return sharepointContentFilesToSync;
  }

  public async downloadFileContent(driveId: string, itemId: string): Promise<Buffer> {
    this.logger.debug(`Downloading file content for item ${itemId} from drive ${driveId}`);
    const maxFileSizeBytes = this.configService.get('processing.maxFileSizeBytes', { infer: true });

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

  public async getAspxPagesForSite(siteId: string): Promise<SharepointContentItem[]> {
    const [siteWebUrl, lists] = await Promise.all([
      this.getSiteWebUrl(siteId),
      this.getSiteLists(siteId),
    ]);

    // Scan ASPX files from SitePages list
    const sitePagesList = lists.find((list) => list.name?.toLowerCase() === 'sitepages');
    if (!sitePagesList?.id) {
      this.logger.warn(
        `Cannot scan Site Pages because SitePages list was not found for site ${siteId}`,
      );
      return [];
    }

    try {
      const aspxSharepointContentItems: SharepointContentItem[] = await this.getAspxListItems(
        siteId,
        sitePagesList.id,
        siteWebUrl,
      );
      this.logger.log(
        `Found ${aspxSharepointContentItems.length} ASPX files from SitePages for site ${siteId}`,
      );
      return aspxSharepointContentItems;
    } catch (error) {
      this.logger.warn(`Failed to scan ASPX files from SitePages for site ${siteId}: ${error}`);
      return [];
    }
  }

  public async getSiteLists(siteId: string): Promise<List[]> {
    try {
      const allLists = await this.paginateGraphApiRequest<List>(`/sites/${siteId}/lists`, (url) =>
        this.graphClient.api(url).select('system,name,id').top(GRAPH_API_PAGE_SIZE).get(),
      );

      this.logger.log(`Found ${allLists.length} lists for site ${siteId}`);

      return allLists;
    } catch (error) {
      this.logger.error(`Failed to fetch lists for site ${siteId}:`, error);
      throw error;
    }
  }

  public async getAspxListItems(
    siteId: string,
    listId: string,
    siteWebUrl: string,
  ): Promise<SharepointContentItem[]> {
    try {
      const aspxItems: SharepointContentItem[] = [];

      const items = await this.paginateGraphApiRequest<ListItem>(
        `/sites/${siteId}/lists/${listId}/items`,
        (url) =>
          this.graphClient
            .api(url)
            .select('id,createdDateTime,lastModifiedDateTime,webUrl,createdBy,lastModifiedBy')
            .expand(
              'fields($select=FileLeafRef,FinanceGPTKnowledge,FileSizeDisplay,_ModerationStatus,Title)',
            )
            .top(GRAPH_API_PAGE_SIZE)
            .get(),
      );

      for (const item of items) {
        if (!this.fileFilterService.isListItemValidForIngestion(item.fields)) continue;

        const aspxSharepointContentItem: SharepointContentItem = {
          itemType: 'listItem',
          item,
          siteId,
          siteWebUrl,
          driveId: listId,
          driveName: 'SitePages',
          folderPath: item.webUrl,
          fileName: getTitle(item.fields),
        };

        aspxItems.push(aspxSharepointContentItem);
      }

      this.logger.log(`Found ${aspxItems.length} ASPX files in SitePages list`);
      return aspxItems;
    } catch (error) {
      this.logger.error(`Failed to fetch ASPX files from SitePages list ${listId}:`, error);
      throw error;
    }
  }

  public async getAspxPageContent(
    siteId: string,
    listId: string,
    itemId: string,
  ): Promise<SitePageContent> {
    this.logger.debug(`Fetching site page content for item ${itemId} from list ${listId}`);

    try {
      const response = await this.makeRateLimitedRequest<ListItemDetailsResponse>(() =>
        this.graphClient
          .api(`/sites/${siteId}/lists/${listId}/items/${itemId}`)
          .select('id')
          .expand('fields($select=CanvasContent1,WikiField,Title)')
          .get(),
      );

      assert(response?.fields, 'MS Graph response missing fields for page content');

      return {
        canvasContent: response.fields.CanvasContent1,
        wikiField: response.fields.WikiField,
        title: response.fields.Title,
      };
    } catch (error) {
      this.logger.error(`Failed to fetch site page content for item ${itemId}:`, error);
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
      const allDrives = await this.paginateGraphApiRequest<Drive>(
        `/sites/${siteId}/drives`,
        (url) => this.graphClient.api(url).top(GRAPH_API_PAGE_SIZE).get(),
      );

      this.logger.log(`Found ${allDrives.length} drives for site ${siteId}`);

      return allDrives;
    } catch (error) {
      this.logger.error(`Failed to fetch drives for site ${siteId}:`, error);
      throw error;
    }
  }

  private async recursivelyFetchDriveItems(
    driveId: string,
    itemId: string,
    siteId: string,
    siteWebUrl: string,
    driveName: string,
    maxFiles?: number,
  ): Promise<SharepointContentItem[]> {
    const sharepointContentItemsToSync: SharepointContentItem[] = [];

    try {
      const allItems = await this.fetchAllDriveItemsInDrive(driveId, itemId);

      for (const driveItem of allItems) {
        // Check if we've reached the file limit for local testing
        if (maxFiles && sharepointContentItemsToSync.length >= maxFiles) {
          this.logger.warn(`Reached file limit of ${maxFiles}, stopping scan in ${itemId}`);
          break;
        }

        if (this.isFolder(driveItem)) {
          const remainingLimit = maxFiles
            ? maxFiles - sharepointContentItemsToSync.length
            : undefined;
          const filesInNestedDrive = await this.recursivelyFetchDriveItems(
            driveId,
            driveItem.id,
            siteId,
            siteWebUrl,
            driveName,
            remainingLimit,
          );

          sharepointContentItemsToSync.push(...filesInNestedDrive);
        } else if (this.fileFilterService.isFileValidForIngestion(driveItem)) {
          const folderPath = this.extractFolderPath(driveItem);
          sharepointContentItemsToSync.push({
            itemType: 'driveItem',
            item: driveItem,
            siteId,
            siteWebUrl,
            driveId,
            driveName,
            folderPath,
            fileName: driveItem.name,
          });
        }
      }

      return sharepointContentItemsToSync;
    } catch (error) {
      this.logger.error(
        `Failed to fetch items for drive ${driveId}, item ${itemId}: ${normalizeError(error).message}`,
      );
      this.logger.warn(`Continuing scan with results collected so far from ${itemId}`);
      return sharepointContentItemsToSync;
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

  private async fetchAllDriveItemsInDrive(driveId: string, itemId: string): Promise<DriveItem[]> {
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

    return this.paginateGraphApiRequest<DriveItem>(
      `/drives/${driveId}/items/${itemId}/children`,
      (url) =>
        this.graphClient
          .api(url)
          .select(selectFields)
          .expand('listItem($expand=fields)')
          .top(GRAPH_API_PAGE_SIZE)
          .get(),
    );
  }

  private async makeRateLimitedRequest<T>(requestFn: () => Promise<T>): Promise<T> {
    return await this.limiter.schedule(async () => await requestFn());
  }

  private async paginateGraphApiRequest<T>(
    initialUrl: string,
    requestBuilder: (url: string) => Promise<GraphApiResponse<T>>,
  ): Promise<T[]> {
    const allItems: T[] = [];
    let nextPageUrl = initialUrl;

    while (true) {
      const response = await this.makeRateLimitedRequest(() => requestBuilder(nextPageUrl));
      const items = response?.value || [];

      allItems.push(...items);

      if (!response['@odata.nextLink']) {
        break;
      }

      nextPageUrl = response['@odata.nextLink'];
    }

    return allItems;
  }

  private isFolder(driveItem: DriveItem): boolean {
    return Boolean(driveItem.folder && driveItem.id);
  }
}
