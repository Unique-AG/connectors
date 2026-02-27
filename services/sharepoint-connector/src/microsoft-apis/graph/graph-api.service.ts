import assert from 'node:assert';
import { Readable } from 'node:stream';
import { Client } from '@microsoft/microsoft-graph-client';
import type { Drive, List } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { Config } from '../../config';
import { GRAPH_API_PAGE_SIZE } from '../../constants/defaults.constants';
import { BottleneckFactory } from '../../utils/bottleneck.factory';
import { getTitle } from '../../utils/list-item.util';
import { sanitizeError } from '../../utils/normalize-error';
import { createSmeared, Smeared } from '../../utils/smeared';
import { FileFilterService } from './file-filter.service';
import { GraphClientFactory } from './graph-client.factory';
import {
  DriveItem,
  GraphApiResponse,
  GroupMember,
  ListColumn,
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

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly configService: ConfigService<Config, true>,
    private readonly fileFilterService: FileFilterService,
    private readonly bottleneckFactory: BottleneckFactory,
  ) {
    this.graphClient = this.graphClientFactory.createClient();

    const msGraphRateLimitPerMinuteThousands = this.configService.get(
      'sharepoint.graphApiRateLimitPerMinuteThousands',
      { infer: true },
    );
    const msGraphRateLimitPerMinute = msGraphRateLimitPerMinuteThousands * 1000;

    this.limiter = this.bottleneckFactory.createLimiter(
      {
        reservoir: msGraphRateLimitPerMinute,
        reservoirRefreshAmount: msGraphRateLimitPerMinute,
        reservoirRefreshInterval: 60000,
      },
      'Graph API',
    );
  }

  public async getAllSiteItems(
    siteId: Smeared,
    syncColumnName: string,
  ): Promise<{ items: SharepointContentItem[]; directories: SharepointDirectoryItem[] }> {
    const logPrefix = `[Site: ${siteId}]`;
    const [aspxPagesResult, filesResult] = await Promise.allSettled([
      this.getAspxPagesForSite(siteId, syncColumnName),
      this.getAllFilesForSite(siteId, syncColumnName),
    ]);

    const sharepointContentItemsToSync: SharepointContentItem[] = [];
    const sharepointDirectoryItemsToSync: SharepointDirectoryItem[] = [];

    if (aspxPagesResult.status === 'fulfilled') {
      sharepointContentItemsToSync.push(...aspxPagesResult.value);
    } else {
      this.logger.error({
        msg: `${logPrefix} Failed to scan pages`,
        siteId,
        error: sanitizeError(aspxPagesResult.reason),
      });
    }

    if (filesResult.status === 'fulfilled') {
      sharepointContentItemsToSync.push(...filesResult.value.items);
      sharepointDirectoryItemsToSync.push(...filesResult.value.directories);
    } else {
      this.logger.error({
        msg: `${logPrefix} Failed to scan drive files`,
        siteId,
        error: sanitizeError(filesResult.reason),
      });
    }

    this.logger.log(
      `${logPrefix} Completed scan. Found ${sharepointContentItemsToSync.length} total items marked for synchronization.`,
    );
    return { items: sharepointContentItemsToSync, directories: sharepointDirectoryItemsToSync };
  }

  public async getAllFilesForSite(
    siteId: Smeared,
    syncColumnName: string,
  ): Promise<{ items: SharepointContentItem[]; directories: SharepointDirectoryItem[] }> {
    const maxFilesToScan = this.configService.get('processing.maxFilesToScan', { infer: true });
    const sharepointContentFilesToSync: SharepointContentItem[] = [];
    const sharepointDirectoryItemsToSync: SharepointDirectoryItem[] = [];
    let totalScanned = 0;
    const LOG_INTERVAL = 20;

    if (maxFilesToScan) {
      this.logger.warn(`File scan limit set to ${maxFilesToScan} files for testing purpose.`);
    }

    const drives = await this.getDrivesForSite(siteId);

    for (const drive of drives) {
      if (!drive.id || !drive.name) {
        continue;
      }

      const remainingLimit = maxFilesToScan ? maxFilesToScan - totalScanned : undefined;
      if (remainingLimit !== undefined && remainingLimit <= 0) {
        this.logger.log(`Reached file scan limit of ${maxFilesToScan}, stopping drive scan`);
        break;
      }

      const { items, directories } = await this.recursivelyFetchDriveItems(
        drive.id,
        'root',
        siteId,
        drive.name,
        syncColumnName,
        remainingLimit,
      );

      sharepointContentFilesToSync.push(...items);
      sharepointDirectoryItemsToSync.push(...directories);
      totalScanned += items.length;

      // Log progress every 20 files
      if (totalScanned % LOG_INTERVAL === 0) {
        this.logger.log(
          `Scanning in progress for site ${siteId}: ${totalScanned} files scanned so far`,
        );
      }

      // Stop scanning if we've reached the limit for testing
      if (maxFilesToScan && totalScanned >= maxFilesToScan) {
        this.logger.log(`Reached file scan limit of ${maxFilesToScan}, stopping scan`);
        break;
      }
    }

    this.logger.log(`Found ${sharepointContentFilesToSync.length} drive files for site ${siteId}`);
    return { items: sharepointContentFilesToSync, directories: sharepointDirectoryItemsToSync };
  }

  public async getFileContentStream(driveId: string, itemId: string): Promise<Readable> {
    const logPrefix = `[DriveId: ${driveId}, ItemId: ${itemId}]`;
    this.logger.debug(`${logPrefix} Getting file content stream`);

    try {
      return await this.makeRateLimitedRequest(async () =>
        Readable.fromWeb(
          await this.graphClient.api(`/drives/${driveId}/items/${itemId}/content`).getStream(),
        ),
      );
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to get file content stream`,
        itemId,
        driveId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  public async getAspxPagesForSite(
    siteId: Smeared,
    syncColumnName: string,
  ): Promise<SharepointContentItem[]> {
    const logPrefix = `[Site: ${siteId}]`;
    const maxFilesToScan = this.configService.get('processing.maxFilesToScan', { infer: true });
    const lists = await this.getSiteLists(siteId);

    if (maxFilesToScan) {
      this.logger.warn(`Items scan limit set to ${maxFilesToScan} items for testing purpose.`);
    }

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
        syncColumnName,
        maxFilesToScan,
      );
      this.logger.log(
        `${logPrefix} Found ${aspxSharepointContentItems.length} ASPX files from SitePages`,
      );
      return aspxSharepointContentItems;
    } catch (error) {
      this.logger.warn({
        msg: `${logPrefix} Failed to scan ASPX files from SitePages`,
        siteId,
        error: sanitizeError(error),
      });
      return [];
    }
  }

  public async getSiteLists(siteId: Smeared): Promise<List[]> {
    const logPrefix = `[Site: ${siteId}]`;

    try {
      const allLists = await this.paginateGraphApiRequest<List>(
        `/sites/${siteId.value}/lists`,
        (url) =>
          this.graphClient
            .api(url)
            .select('system,name,id,displayName')
            .top(GRAPH_API_PAGE_SIZE)
            .get(),
      );

      this.logger.log(`${logPrefix} Found ${allLists.length} lists`);

      return allLists;
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to fetch lists. Check Sites.Selected permission.`,
        siteId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  /**
   * Fetch all columns for a specific SharePoint list.
   * Documentation: https://learn.microsoft.com/en-us/graph/api/list-list-columns
   */
  public async getListColumns(siteId: Smeared, listId: string): Promise<ListColumn[]> {
    const logPrefix = `[Site: ${siteId}, List: ${listId}]`;

    try {
      const columns = await this.paginateGraphApiRequest<ListColumn>(
        `/sites/${siteId.value}/lists/${listId}/columns`,
        (url) => this.graphClient.api(url).select('id,name,displayName').get(),
      );

      this.logger.log(`${logPrefix} Found ${columns.length} columns`);

      return columns;
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to fetch list columns`,
        siteId,
        listId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  public async getListItems(
    siteId: Smeared,
    listId: string,
    options: { select?: string; expand?: string } = {},
  ): Promise<ListItem[]> {
    const { select, expand } = options;
    return await this.paginateGraphApiRequest<ListItem>(
      `/sites/${siteId.value}/lists/${listId}/items`,
      (url) => {
        let requestBuilder = this.graphClient.api(url);
        if (select) {
          requestBuilder = requestBuilder.select(select);
        }
        if (expand) {
          requestBuilder = requestBuilder.expand(expand);
        }
        return requestBuilder.top(GRAPH_API_PAGE_SIZE).get();
      },
    );
  }

  public async getAspxListItems(
    siteId: Smeared,
    listId: string,
    syncColumnName: string,
    maxItemsToScan?: number,
  ): Promise<SharepointContentItem[]> {
    const logPrefix = `[Site: ${siteId}]`;
    try {
      const aspxItems: SharepointContentItem[] = [];

      const items = await this.getListItems(siteId, listId, {
        select: 'id,createdDateTime,lastModifiedDateTime,webUrl,createdBy,lastModifiedBy',
        expand: `fields($select=${syncColumnName},FileLeafRef,FileSizeDisplay,_ModerationStatus,Title,AuthorLookupId,EditorLookupId)`,
      });

      for (const item of items) {
        if (!this.fileFilterService.isListItemValidForIngestion(item.fields, syncColumnName)) {
          continue;
        }

        const aspxSharepointContentItem: SharepointContentItem = {
          itemType: 'listItem',
          item,
          siteId,
          driveId: listId,
          driveName: 'SitePages',
          folderPath: item.webUrl,
          fileName: getTitle(item.fields),
        };

        aspxItems.push(aspxSharepointContentItem);

        if (maxItemsToScan && aspxItems.length >= maxItemsToScan) {
          this.logger.log(
            `${logPrefix} Reached scan limit of ${maxItemsToScan} items in SitePages list ${listId}, stopping scan`,
          );
          break;
        }
      }

      this.logger.log(`${logPrefix} Found ${aspxItems.length} ASPX files in SitePages list`);
      return aspxItems;
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to fetch ASPX files from SitePages list`,
        siteId,
        listId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  public async getAspxPageContent(
    siteId: Smeared,
    listId: string,
    itemId: string,
  ): Promise<SitePageContent> {
    const logPrefix = `[Site: ${siteId}, Item: ${itemId}]`;
    this.logger.debug(`${logPrefix} Fetching site page content from list ${listId}`);

    try {
      const response = await this.makeRateLimitedRequest<ListItemDetailsResponse>(() =>
        this.graphClient
          .api(`/sites/${siteId.value}/lists/${listId}/items/${itemId}`)
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
      this.logger.error({
        msg: `${logPrefix} Failed to fetch site page content for item`,
        itemId,
        siteId,
        listId,
        error: sanitizeError(error),
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
    siteId: Smeared,
    listId: string,
    itemId: string,
  ): Promise<SimplePermission[]> {
    return await this.paginateGraphApiRequest<SimplePermission>(
      `/sites/${siteId.value}/lists/${listId}/items/${itemId}/permissions`,
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

  public async getSiteWebUrl(siteId: Smeared): Promise<string> {
    try {
      const site = await this.makeRateLimitedRequest(() =>
        this.graphClient.api(`/sites/${siteId.value}`).select('webUrl').get(),
      );

      return site.webUrl;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to fetch site info. Check Sites.Selected permission.',
        siteId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  public async getSiteName(siteId: Smeared): Promise<Smeared> {
    const siteWebUrl = await this.getSiteWebUrl(siteId);
    const { pathname } = new URL(siteWebUrl);
    const sitesPrefix = '/sites/';
    const sitesIndex = pathname.indexOf(sitesPrefix);
    assert.notEqual(sitesIndex, -1, `Site name not found for site ${siteId}`);
    const siteName = decodeURIComponent(pathname.substring(sitesIndex + sitesPrefix.length));
    return createSmeared(siteName);
  }

  private async getDrivesForSite(siteId: Smeared): Promise<Drive[]> {
    const logPrefix = `[Site: ${siteId}]`;
    try {
      const allDrives = await this.paginateGraphApiRequest<Drive>(
        `/sites/${siteId.value}/drives`,
        (url) => this.graphClient.api(url).top(GRAPH_API_PAGE_SIZE).get(),
      );

      this.logger.log(`${logPrefix} Found ${allDrives.length} drives`);

      return allDrives;
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to fetch drives`,
        siteId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  private async recursivelyFetchDriveItems(
    driveId: string,
    itemId: string,
    siteId: Smeared,
    driveName: string,
    syncColumnName: string,
    maxFiles?: number,
  ): Promise<{ items: SharepointContentItem[]; directories: SharepointDirectoryItem[] }> {
    const sharepointContentItemsToSync: SharepointContentItem[] = [];
    const sharepointDirectoryItemsToSync: SharepointDirectoryItem[] = [];
    try {
      const allItems = await this.fetchAllDriveItemsInDrive(driveId, itemId);

      for (const driveItem of allItems) {
        // Check if we've reached the file limit for local testing
        if (maxFiles && sharepointContentItemsToSync.length >= maxFiles) {
          this.logger.warn(
            `Reached file limit of ${maxFiles}, stopping scan in drive ${driveId}, item ${itemId} for site ${siteId}`,
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
            driveName,
            syncColumnName,
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
            driveId,
            driveName,
            folderPath: this.extractFolderPath(driveItem),
            fileName: driveItem.name,
          });
          sharepointDirectoryItemsToSync.push(...directories);
        } else if (this.fileFilterService.isFileValidForIngestion(driveItem, syncColumnName)) {
          const folderPath = this.extractFolderPath(driveItem);
          sharepointContentItemsToSync.push({
            itemType: 'driveItem',
            item: driveItem,
            siteId,
            driveId,
            driveName,
            folderPath,
            fileName: driveItem.name,
          });
        }
      }

      return { items: sharepointContentItemsToSync, directories: sharepointDirectoryItemsToSync };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to fetch items for drive',
        driveId,
        itemId,
        error: sanitizeError(error),
      });

      this.logger.warn(
        `Continuing scan with results collected so far from drive ${driveId}, item ${itemId} for site ${siteId}`,
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
