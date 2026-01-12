import assert from 'node:assert';
import { Readable } from 'node:stream';
import { Client } from '@microsoft/microsoft-graph-client';
import type { Drive, List } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { z } from 'zod';
import { Config } from '../../config';
import { SiteConfigSchema } from '../../config/tenant-config.schema';

// Derive type from schema instead of importing it
type SiteConfig = z.infer<typeof SiteConfigSchema>;

import { GRAPH_API_PAGE_SIZE } from '../../constants/defaults.constants';
import { BottleneckFactory } from '../../utils/bottleneck.factory';
import { getTitle } from '../../utils/list-item.util';
import { shouldConcealLogs, smear } from '../../utils/logging.util';
import { sanitizeError } from '../../utils/normalize-error';
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

  /**
   * Loads site configurations from the specified source (config file or SharePoint list).
   */
  public async loadSitesConfiguration(): Promise<SiteConfig[]> {
    const sharepointConfig = this.configService.get('sharepoint', { infer: true });

    if (sharepointConfig.sitesSource === 'config_file') {
      this.logger.log('Loading sites configuration from static YAML');
      return sharepointConfig.sites;
    }

    this.logger.debug('Loading sites configuration from SharePoint list');
    return await this.fetchSitesFromSharePointList(sharepointConfig.sharepointList);
  }

  /**
   * Fetch site configurations from a SharePoint list.
   * In order to fetch the sites configuration from a SharePoint list, we need to:
   * 1. Get the list ID by display name in the specified site
   * 2. Fetch the list items
   * 3. Transform the list items to SiteConfig and validate with Zod
   * Returns the SiteConfig array
   */
  public async fetchSitesFromSharePointList(sharepointList: {
    siteId: string;
    listDisplayName: string;
  }): Promise<SiteConfig[]> {
    const { siteId, listDisplayName } = sharepointList;
    const logSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;

    this.logger.debug(
      `Fetching sites configuration from site: ${logSiteId}, list: ${listDisplayName}`,
    );

    // Unfortunately we cannot filter by list name using ms graph so we need to fetch all lists.
    const lists = await this.getSiteLists(siteId);
    const matchingList = lists.find((list) => list.displayName === listDisplayName);

    assert.ok(matchingList?.id, `List "${listDisplayName}" not found in site ${logSiteId}`);
    const listId = matchingList.id;

    this.logger.debug(`Resolved list ID: ${listId} for list: ${listDisplayName}`);

    const [listItems, columns] = await Promise.all([
      this.getListItems(siteId, listId, { expand: 'fields' }),
      this.getListColumns(siteId, listId),
    ]);

    this.logger.log(
      `Fetched ${listItems.length} items and ${columns.length} columns from SharePoint list`,
    );

    const nameMap = this.createDisplayNameToInternalNameMap(columns);

    const siteConfigs = listItems.map((item, index) =>
      this.transformListItemToSiteConfig(item, index, nameMap),
    );

    this.logger.log(
      `Successfully loaded ${siteConfigs.length} site configurations from SharePoint list`,
    );
    return siteConfigs;
  }

  private createDisplayNameToInternalNameMap(columns: ListColumn[]): Record<string, string> {
    const map: Record<string, string> = {};
    for (const column of columns) {
      map[column.displayName] = column.name;
    }
    return map;
  }

  private transformListItemToSiteConfig(
    item: ListItem,
    index: number,
    nameMap: Record<string, string>,
  ): SiteConfig {
    try {
      const fields = item.fields;

      const getFieldValue = (displayName: string) => {
        const internalName = nameMap[displayName];
        return internalName ? fields[internalName] : undefined;
      };

      const siteConfig = {
        siteId: getFieldValue('siteId'),
        syncColumnName: getFieldValue('syncColumnName'),
        ingestionMode: getFieldValue('ingestionMode'),
        scopeId: getFieldValue('uniqueScopeId'),
        maxFilesToIngest: getFieldValue('maxFilesToIngest'),
        storeInternally: getFieldValue('storeInternally'),
        syncStatus: getFieldValue('syncStatus'),
        syncMode: getFieldValue('syncMode'),
        permissionsInheritanceMode: getFieldValue('permissionsInheritanceMode'),
      };

      return SiteConfigSchema.parse(siteConfig);
    } catch (error) {
      this.logger.error({
        msg: `Failed to transform list item at index ${index} to SiteConfig`,
        itemId: item.id,
        error: sanitizeError(error),
      });
      throw new Error(
        `Invalid site configuration at row ${index + 1}: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  public async getAllSiteItems(
    siteId: string,
    syncColumnName: string,
  ): Promise<{ items: SharepointContentItem[]; directories: SharepointDirectoryItem[] }> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
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
        siteId: this.shouldConcealLogs ? smear(siteId) : siteId,
        error: sanitizeError(aspxPagesResult.reason),
      });
    }

    if (filesResult.status === 'fulfilled') {
      sharepointContentItemsToSync.push(...filesResult.value.items);
      sharepointDirectoryItemsToSync.push(...filesResult.value.directories);
    } else {
      this.logger.error({
        msg: `${logPrefix} Failed to scan drive files`,
        siteId: this.shouldConcealLogs ? smear(siteId) : siteId,
        error: sanitizeError(filesResult.reason),
      });
    }

    this.logger.log(
      `${logPrefix} Completed scan. Found ${sharepointContentItemsToSync.length} total items marked for synchronization.`,
    );
    return { items: sharepointContentItemsToSync, directories: sharepointDirectoryItemsToSync };
  }

  public async getAllFilesForSite(
    siteId: string,
    syncColumnName: string,
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

    const drives = await this.getDrivesForSite(siteId);

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
    siteId: string,
    syncColumnName: string,
  ): Promise<SharepointContentItem[]> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
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
        siteId: this.shouldConcealLogs ? smear(siteId) : siteId,
        error: sanitizeError(error),
      });
      return [];
    }
  }

  public async getSiteLists(siteId: string): Promise<List[]> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;

    try {
      const allLists = await this.paginateGraphApiRequest<List>(`/sites/${siteId}/lists`, (url) =>
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
        siteId: this.shouldConcealLogs ? smear(siteId) : siteId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  /**
   * Fetch all columns for a specific SharePoint list.
   * Documentation: https://learn.microsoft.com/en-us/graph/api/list-list-columns
   */
  public async getListColumns(siteId: string, listId: string): Promise<ListColumn[]> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}, List: ${listId}]`;

    try {
      const columns = await this.paginateGraphApiRequest<ListColumn>(
        `/sites/${siteId}/lists/${listId}/columns`,
        (url) => this.graphClient.api(url).select('id,name,displayName').get(),
      );

      this.logger.log(`${logPrefix} Found ${columns.length} columns`);

      return columns;
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to fetch list columns`,
        siteId: this.shouldConcealLogs ? smear(siteId) : siteId,
        listId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  public async getListItems(
    siteId: string,
    listId: string,
    options: { select?: string; expand?: string } = {},
  ): Promise<ListItem[]> {
    const { select, expand } = options;
    return await this.paginateGraphApiRequest<ListItem>(
      `/sites/${siteId}/lists/${listId}/items`,
      (url) => {
        let builder = this.graphClient.api(url);
        if (select) builder = builder.select(select);
        if (expand) builder = builder.expand(expand);
        return builder.top(GRAPH_API_PAGE_SIZE).get();
      },
    );
  }

  public async getAspxListItems(
    siteId: string,
    listId: string,
    syncColumnName: string,
    maxItemsToScan?: number,
  ): Promise<SharepointContentItem[]> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
    try {
      const aspxItems: SharepointContentItem[] = [];

      const items = await this.getListItems(siteId, listId, {
        select: 'id,createdDateTime,lastModifiedDateTime,webUrl,createdBy,lastModifiedBy',
        expand: `fields($select=${syncColumnName},FileLeafRef,FileSizeDisplay,_ModerationStatus,Title,AuthorLookupId,EditorLookupId)`,
      });

      for (const item of items) {
        if (!this.fileFilterService.isListItemValidForIngestion(item.fields, syncColumnName))
          continue;

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
        siteId: this.shouldConcealLogs ? smear(siteId) : siteId,
        listId,
        error: sanitizeError(error),
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
      this.logger.error({
        msg: 'Failed to fetch site page content for item',
        itemId,
        siteId: this.shouldConcealLogs ? smear(siteId) : siteId,
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
      this.logger.error({
        msg: 'Failed to fetch site info. Check Sites.Selected permission.',
        siteId: loggedSiteId,
        error: sanitizeError(error),
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
      this.logger.error({
        msg: `${logPrefix} Failed to fetch drives`,
        siteId: this.shouldConcealLogs ? smear(siteId) : siteId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  private async recursivelyFetchDriveItems(
    driveId: string,
    itemId: string,
    siteId: string,
    driveName: string,
    syncColumnName: string,
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
