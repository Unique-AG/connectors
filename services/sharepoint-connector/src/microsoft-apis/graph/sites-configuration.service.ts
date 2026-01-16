import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { z } from 'zod';
import { Config } from '../../config';
import { SiteConfigSchema } from '../../config/sharepoint.schema';
import { shouldConcealLogs, smear } from '../../utils/logging.util';
import { normalizeError, sanitizeError } from '../../utils/normalize-error';
import { GraphApiService } from './graph-api.service';
import { ListColumn, ListItem } from './types/sharepoint.types';

type SiteConfig = z.infer<typeof SiteConfigSchema>;

@Injectable()
export class SitesConfigurationService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly graphApiService: GraphApiService,
    private readonly configService: ConfigService<Config, true>,
  ) {
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
    const lists = await this.graphApiService.getSiteLists(siteId);

    // Very important step to check by displayName and not name because in SharePoint when a column is renamed only displayName is updated
    const matchingList = lists.find((list) => list.displayName === listDisplayName);

    assert.ok(matchingList?.id, `List "${listDisplayName}" not found in site ${logSiteId}`);
    const listId = matchingList.id;

    this.logger.debug(`Resolved list ID: ${listId} for list: ${listDisplayName}`);

    const [listItems, columns] = await Promise.all([
      this.graphApiService.getListItems(siteId, listId, { expand: 'fields' }),
      this.graphApiService.getListColumns(siteId, listId),
    ]);

    this.logger.log(
      `Fetched ${listItems.length} items and ${columns.length} columns from SharePoint list`,
    );

    const displayNameToNameMap = this.createDisplayNameToNameMap(columns);

    const siteConfigs = listItems.map((item, index) =>
      this.transformListItemToSiteConfig(item, index, displayNameToNameMap),
    );

    this.logger.log(
      `Successfully loaded ${siteConfigs.length} site configurations from SharePoint list`,
    );
    return siteConfigs;
  }

  private createDisplayNameToNameMap(columns: ListColumn[]): Record<string, string> {
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
        `Invalid site configuration at row ${index + 1}: ${normalizeError(error).message}`,
      );
    }
  }
}
