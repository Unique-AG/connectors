import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { map, partition, pipe, prop } from 'remeda';
import { Config } from '../../config';
import {
  type PartialSiteConfig,
  PartialSiteConfigSchema,
  type SiteConfig,
} from '../../config/sharepoint.schema';
import { mergeSiteWithDefaults } from '../../config/site-config-merger';
import { normalizeError, sanitizeError } from '../../utils/normalize-error';
import { Smeared } from '../../utils/smeared';
import { GraphApiService } from './graph-api.service';
import { ListColumn, ListItem } from './types/sharepoint.types';

@Injectable()
export class SitesConfigurationService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphApiService: GraphApiService,
    private readonly configService: ConfigService<Config, true>,
  ) {}

  /**
   * Loads site configurations from the specified source (config file or SharePoint list).
   */
  public async loadSitesConfiguration(): Promise<SiteConfig[]> {
    const sharepointConfig = this.configService.get('sharepoint', { infer: true });

    if (sharepointConfig.sitesSource === 'config_file') {
      this.logger.log('Loading sites configuration from YAML file');
      return sharepointConfig.sites.map((site, index) =>
        mergeSiteWithDefaults(
          site,
          sharepointConfig.siteDefaults,
          `config_file row ${index + 1} (siteId: ${site.siteId})`,
        ),
      );
    }

    this.logger.debug('Loading sites configuration from SharePoint list');
    const sites = await this.fetchSitesFromSharePointList({
      siteId: sharepointConfig.sharepointList.siteId,
      listId: sharepointConfig.sharepointList.listId,
    });
    return sites;
  }

  private async fetchSitesFromSharePointList(sharepointList: {
    siteId: Smeared;
    listId: string;
  }): Promise<SiteConfig[]> {
    const { siteDefaults } = this.configService.get('sharepoint', { infer: true });
    const { siteId, listId } = sharepointList;

    this.logger.debug(`Fetching sites configuration from site: ${siteId}, list: ${listId}`);

    const [listItems, columns] = await Promise.all([
      this.graphApiService.getListItems(siteId, listId, { expand: 'fields' }),
      this.graphApiService.getListColumns(siteId, listId),
    ]);

    this.logger.log(
      `Fetched ${listItems.length} items and ${columns.length} columns from SharePoint list`,
    );

    const displayNameToNameMap = this.createDisplayNameToNameMap(columns);

    assert.ok(
      displayNameToNameMap.siteId,
      "SharePoint list has no column with display name 'siteId'. Was the column renamed?",
    );

    // A row without a siteId cannot refer to any site, so skipping it loses nothing. Such rows are
    // typically added by accident and must not fail the whole sync. Rows that have a siteId but are
    // otherwise invalid still fail loudly, so a misconfigured site is never silently dropped.
    const [rowsWithSiteId, rowsWithoutSiteId] = pipe(
      listItems,
      map((item, index) => ({ item, rowNumber: index + 1 })),
      partition(({ item }) => Boolean(readField(item, 'siteId', displayNameToNameMap))),
    );

    if (rowsWithoutSiteId.length > 0) {
      const skippedRowNumbers = rowsWithoutSiteId.map(prop('rowNumber')).join(', ');
      this.logger.warn({
        msg: `Skipping SharePoint list rows without a siteId: ${skippedRowNumbers}`,
        itemIds: rowsWithoutSiteId.map(prop('item', 'id')),
      });
    }

    const siteConfigs = rowsWithSiteId.map(({ item, rowNumber }) => {
      const partial = this.transformListItemToSiteConfig(item, rowNumber, displayNameToNameMap);
      return mergeSiteWithDefaults(
        partial,
        siteDefaults,
        `sharepoint_list row ${rowNumber} (siteId: ${partial.siteId})`,
      );
    });

    this.logger.log(
      `Successfully loaded ${siteConfigs.length} site configurations from SharePoint list`,
    );
    return siteConfigs;
  }

  // We need the mapping because in the API name stays the same, so after rename the old incorrect
  // name will still be visible in the name field, when the displayName will change.
  private createDisplayNameToNameMap(columns: ListColumn[]): Record<string, string> {
    const map: Record<string, string> = {};
    for (const column of columns) {
      map[column.displayName] = column.name;
    }
    return map;
  }

  private transformListItemToSiteConfig(
    item: ListItem,
    rowNumber: number,
    nameMap: Record<string, string>,
  ): PartialSiteConfig {
    try {
      const getFieldValue = (displayName: string) => readField(item, displayName, nameMap);

      const siteConfig = {
        siteId: getFieldValue('siteId'),
        syncColumnName: getFieldValue('syncColumnName'),
        itemNameColumnName: getFieldValue('itemNameColumnName'),
        ingestionMode: getFieldValue('ingestionMode'),
        scopeId: getFieldValue('uniqueScopeId'),
        // when unset sharepoint list item, maxFilesToIngest is set to 0
        maxFilesToIngest: getFieldValue('maxFilesToIngest') || undefined,
        storeInternally: getFieldValue('storeInternally'),
        syncStatus: getFieldValue('syncStatus'),
        syncMode: getFieldValue('syncMode'),
        permissionsInheritanceMode: getFieldValue('permissionsInheritanceMode'),
        subsitesScan: getFieldValue('subsitesScan'),
        listAttachmentsScan: getFieldValue('listAttachmentsScan'),
      };

      return PartialSiteConfigSchema.parse(siteConfig);
    } catch (error) {
      this.logger.error({
        msg: `Failed to transform list item at row ${rowNumber} to PartialSiteConfig`,
        itemId: item.id,
        error: sanitizeError(error),
      });
      throw new Error(
        `Invalid site configuration at row ${rowNumber}: ${normalizeError(error).message}`,
      );
    }
  }
}

function readField(item: ListItem, displayName: string, nameMap: Record<string, string>): unknown {
  const internalName = nameMap[displayName];
  const value = internalName ? item.fields[internalName] : undefined;
  return typeof value === 'string' ? value.trim() : value;
}
