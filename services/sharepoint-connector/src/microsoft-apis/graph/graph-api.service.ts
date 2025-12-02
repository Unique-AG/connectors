import assert from 'node:assert';
import { Client } from '@microsoft/microsoft-graph-client';
import type { Drive, List } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { Config } from '../../config';
import { GRAPH_API_PAGE_SIZE } from '../../constants/defaults.constants';
import { BottleneckFactory } from '../../utils/bottleneck.factory';
import { getTitle } from '../../utils/list-item.util';
import { shouldConcealLogs, smear } from '../../utils/logging.util';
import { normalizeError } from '../../utils/normalize-error';
import { FileFilterService } from './file-filter.service';
import { GraphClientFactory } from './graph-client.factory';
import {
  DriveItem,
  GraphApiResponse,
  GroupMember,
  ListItem,
  ListItemDetailsResponse,
  SimplePermission,
  SitePageContent,
} from './types/sharepoint.types';
import {
  SharepointContentItem,
  SharepointDirectoryItem,
} from './types/sharepoint-content-item.interface';

@Injectable()
export class GraphApiService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly graphClient: Client;
  private readonly limiter: Bottleneck;
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly configService: ConfigService<Config, true>,
    private readonly fileFilterService: FileFilterService,
    private readonly bottleneckFactory: BottleneckFactory,
  ) {
    this.graphClient = this.graphClientFactory.createClient();

    const msGraphRateLimitPerMinute = this.configService.get(
      'sharepoint.graphApiRateLimitPerMinute',
      { infer: true },
    );

    this.limiter = this.bottleneckFactory.createLimiter(
      {
        reservoir: msGraphRateLimitPerMinute,
        reservoirRefreshAmount: msGraphRateLimitPerMinute,
        reservoirRefreshInterval: 60000,
      },
      'Graph API',
    );

    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

  public async getAllSiteItems(
    siteId: string,
  ): Promise<{ items: SharepointContentItem[]; directories: SharepointDirectoryItem[] }> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
    const [aspxPagesResult, filesResult] = await Promise.allSettled([
      this.getAspxPagesForSite(siteId),
      this.getAllFilesForSite(siteId),
    ]);

    const sharepointContentItemsToSync: SharepointContentItem[] = [];
    const sharepointDirectoryItemsToSync: SharepointDirectoryItem[] = [];

    if (aspxPagesResult.status === 'fulfilled') {
      sharepointContentItemsToSync.push(...aspxPagesResult.value);
    } else {
      this.logger.error(`${logPrefix} Failed to scan pages:`, aspxPagesResult.reason);
    }

    if (filesResult.status === 'fulfilled') {
      sharepointContentItemsToSync.push(...filesResult.value.items);
      sharepointDirectoryItemsToSync.push(...filesResult.value.directories);
    } else {
      this.logger.error(`${logPrefix} Failed to scan drive files:`, filesResult.reason);
    }

    this.logger.log(
      `${logPrefix} Completed scan. Found ${sharepointContentItemsToSync.length} total items marked for synchronization.`,
    );
    return { items: sharepointContentItemsToSync, directories: sharepointDirectoryItemsToSync };
  }

  public async getAllFilesForSite(
    siteId: string,
  ): Promise<{ items: SharepointContentItem[]; directories: SharepointDirectoryItem[] }> {
    const loggedSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
    const maxFilesToScan = this.configService.get('processing.maxFilesToScan', { infer: true });
    const sharepointContentFilesToSync: SharepointContentItem[] = [];
    const sharepointDirectoryItemsToSync: SharepointDirectoryItem[] = [];
    let totalScanned = 0;
    const LOG_INTERVAL = 20;

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

      const { items, directories } = await this.recursivelyFetchDriveItems(
        drive.id,
        'root',
        siteId,
        siteWebUrl,
        drive.name,
        remainingLimit,
      );

      sharepointContentFilesToSync.push(...items);
      sharepointDirectoryItemsToSync.push(...directories);
      totalScanned += items.length;

      // Log progress every 20 files
      if (totalScanned % LOG_INTERVAL === 0) {
        this.logger.log(
          `Scanning in progress for site ${loggedSiteId}: ${totalScanned} files scanned so far`,
        );
      }

      // Stop scanning if we've reached the limit for testing
      if (maxFilesToScan && totalScanned >= maxFilesToScan) {
        this.logger.log(`Reached file scan limit of ${maxFilesToScan}, stopping scan`);
        break;
      }
    }

    this.logger.log(
      `Found ${sharepointContentFilesToSync.length} drive files for site ${loggedSiteId}`,
    );
    return { items: sharepointContentFilesToSync, directories: sharepointDirectoryItemsToSync };
  }

  public async downloadFileContent(driveId: string, itemId: string): Promise<Buffer> {
    const logPrefix = `[DriveId: ${driveId}, ItemId: ${itemId}]`;
    this.logger.debug(`${logPrefix} Downloading file content`);
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
          assert.fail(`${logPrefix} File size exceeds maximum limit of ${maxFileSizeBytes} bytes.`);
        }

        chunks.push(bufferChunk);
      }

      // TODO (UN-14011) replace with a metric
      this.logger.debug(`${logPrefix} Starting Buffer.concat for ${chunks.length} chunks`);
      const concatStartTime = Date.now();

      const finalBuffer = Buffer.concat(chunks);

      this.logger.debug(
        `${logPrefix} Buffer.concat completed in ${Date.now() - concatStartTime}ms`,
      );

      return finalBuffer;
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error({
        msg: `${logPrefix} Failed to download file content: ${normalizedError.message}`,
        itemId,
        driveId,
        error,
      });
      throw error;
    }
  }

  public async getAspxPagesForSite(siteId: string): Promise<SharepointContentItem[]> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
    const [siteWebUrl, lists] = await Promise.all([
      this.getSiteWebUrl(siteId),
      this.getSiteLists(siteId),
    ]);

    // Scan ASPX files from SitePages list
    const sitePagesList = lists.find((list) => list.name?.toLowerCase() === 'sitepages');
    if (!sitePagesList?.id) {
      this.logger.warn(`${logPrefix} Cannot scan Site Pages because SitePages list was not found`);
      return [];
    }

    try {
      const aspxSharepointContentItems: SharepointContentItem[] = await this.getAspxListItems(
        siteId,
        sitePagesList.id,
        siteWebUrl,
      );
      this.logger.log(
        `${logPrefix} Found ${aspxSharepointContentItems.length} ASPX files from SitePages`,
      );
      return aspxSharepointContentItems;
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.warn(
        `${logPrefix} Failed to scan ASPX files from SitePages: ${normalizedError.message}`,
      );
      return [];
    }
  }

  public async getSiteLists(siteId: string): Promise<List[]> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;

    try {
      const allLists = await this.paginateGraphApiRequest<List>(`/sites/${siteId}/lists`, (url) =>
        this.graphClient.api(url).select('system,name,id').top(GRAPH_API_PAGE_SIZE).get(),
      );

      this.logger.log(`${logPrefix} Found ${allLists.length} lists`);

      return allLists;
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error({
        msg: `${logPrefix} Failed to fetch lists. Check Sites.Selected permission. ${normalizedError.message}`,
        error,
      });
      throw error;
    }
  }

  public async getAspxListItems(
    siteId: string,
    listId: string,
    siteWebUrl: string,
  ): Promise<SharepointContentItem[]> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
    try {
      const aspxItems: SharepointContentItem[] = [];

      const items = await this.paginateGraphApiRequest<ListItem>(
        `/sites/${siteId}/lists/${listId}/items`,
        (url) =>
          this.graphClient
            .api(url)
            .select('id,createdDateTime,lastModifiedDateTime,webUrl,createdBy,lastModifiedBy')
            .expand(
              'fields($select=FileLeafRef,FinanceGPTKnowledge,FileSizeDisplay,_ModerationStatus,Title,AuthorLookupId,EditorLookupId)',
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

      this.logger.log(`${logPrefix} Found ${aspxItems.length} ASPX files in SitePages list`);
      return aspxItems;
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error({
        msg: `${logPrefix} Failed to fetch ASPX files from SitePages list: ${normalizedError.message}`,
        error,
      });
      throw error;
    }
  }

  public async getAspxPageContent(
    siteId: string,
    listId: string,
    itemId: string,
  ): Promise<SitePageContent> {
    const logPrefix = `[ItemId: ${itemId}]`;
    this.logger.debug(`${logPrefix} Fetching site page content from list ${listId}`);

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
      const normalizedError = normalizeError(error);
      this.logger.error({
        msg: `Failed to fetch site page content for item ${itemId}: ${normalizedError.message}`,
        error,
      });
      throw error;
    }
  }

  public async getDriveItemPermissions(
    driveId: string,
    itemId: string,
  ): Promise<SimplePermission[]> {
    return await this.paginateGraphApiRequest<SimplePermission>(
      `/drives/${driveId}/items/${itemId}/permissions`,
      (url) =>
        this.graphClient
          .api(url)
          .select('id,grantedToV2,grantedToIdentitiesV2')
          .top(GRAPH_API_PAGE_SIZE)
          .get(),
    );
  }

  public async getListItemPermissions(
    siteId: string,
    listId: string,
    itemId: string,
  ): Promise<SimplePermission[]> {
    return await this.paginateGraphApiRequest<SimplePermission>(
      `/sites/${siteId}/lists/${listId}/items/${itemId}/permissions`,
      (url) =>
        this.graphClient
          .api(url)
          .select('id,grantedToV2,grantedToIdentitiesV2')
          .version('beta')
          .top(GRAPH_API_PAGE_SIZE)
          .get(),
    );
  }

  public async getGroupMembers(groupId: string): Promise<GroupMember[]> {
    return await this.paginateGraphApiRequest<GroupMember>(`/groups/${groupId}/members`, (url) =>
      this.graphClient
        .api(url)
        .select(['id', 'displayName', 'mail', 'userPrincipalName'])
        .top(GRAPH_API_PAGE_SIZE)
        .get(),
    );
  }

  public async getGroupOwners(groupId: string): Promise<GroupMember[]> {
    return await this.paginateGraphApiRequest<GroupMember>(`/groups/${groupId}/owners`, (url) =>
      this.graphClient
        .api(url)
        .select(['id', 'displayName', 'mail', 'userPrincipalName'])
        .top(GRAPH_API_PAGE_SIZE)
        .get(),
    );
  }

  public async getSiteWebUrl(siteId: string): Promise<string> {
    const loggedSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
    try {
      const site = await this.makeRateLimitedRequest(() =>
        this.graphClient.api(`/sites/${siteId}`).select('webUrl').get(),
      );

      return site.webUrl;
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error({
        msg: `Failed to fetch site info for ${loggedSiteId}. Check Sites.Selected permission.  ${normalizedError.message}`,
        error,
      });
      throw error;
    }
  }

  public async getSiteName(siteId: string): Promise<string> {
    const siteWebUrl = await this.getSiteWebUrl(siteId);
    return (
      siteWebUrl.split('/').pop() ??
      assert.fail(`Site name not found for site ${this.shouldConcealLogs ? smear(siteId) : siteId}`)
    );
  }

  private async getDrivesForSite(siteId: string): Promise<Drive[]> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
    try {
      const allDrives = await this.paginateGraphApiRequest<Drive>(
        `/sites/${siteId}/drives`,
        (url) => this.graphClient.api(url).top(GRAPH_API_PAGE_SIZE).get(),
      );

      this.logger.log(`${logPrefix} Found ${allDrives.length} drives`);

      return allDrives;
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error({
        msg: `${logPrefix} Failed to fetch drives: ${normalizedError.message}`,
        error,
      });
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
  ): Promise<{ items: SharepointContentItem[]; directories: SharepointDirectoryItem[] }> {
    const loggedSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
    const sharepointContentItemsToSync: SharepointContentItem[] = [];
    const sharepointDirectoryItemsToSync: SharepointDirectoryItem[] = [];
    try {
      const allItems = await this.fetchAllDriveItemsInDrive(driveId, itemId);

      for (const driveItem of allItems) {
        // Check if we've reached the file limit for local testing
        if (maxFiles && sharepointContentItemsToSync.length >= maxFiles) {
          this.logger.warn(
            `Reached file limit of ${maxFiles}, stopping scan in drive ${driveId}, item ${itemId} for site ${loggedSiteId}`,
          );
          break;
        }

        if (this.isFolder(driveItem)) {
          const remainingLimit = maxFiles
            ? maxFiles - sharepointContentItemsToSync.length
            : undefined;
          const { items, directories } = await this.recursivelyFetchDriveItems(
            driveId,
            driveItem.id,
            siteId,
            siteWebUrl,
            driveName,
            remainingLimit,
          );

          // We simply do not care about subtree of the site that contains no files to sync.
          if (items.length === 0) {
            continue;
          }

          sharepointContentItemsToSync.push(...items);
          sharepointDirectoryItemsToSync.push({
            itemType: 'directory',
            item: driveItem,
            siteId,
            siteWebUrl,
            driveId,
            driveName,
            folderPath: this.extractFolderPath(driveItem),
            fileName: driveItem.name,
          });
          sharepointDirectoryItemsToSync.push(...directories);
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

      return { items: sharepointContentItemsToSync, directories: sharepointDirectoryItemsToSync };
    } catch (error) {
      this.logger.error(
        `Failed to fetch items for drive ${driveId}, item ${itemId}: ${normalizeError(error).message}`,
      );

      this.logger.warn(
        `Continuing scan with results collected so far from drive ${driveId}, item ${itemId} for site ${loggedSiteId}`,
      );
      return { items: sharepointContentItemsToSync, directories: sharepointDirectoryItemsToSync };
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
      'createdDateTime',
      'lastModifiedDateTime',
      'createdBy',
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
