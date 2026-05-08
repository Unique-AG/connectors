import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
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

    const siteConfigs = listItems.map((item, index) => {
      const partial = this.transformListItemToSiteConfig(item, index, displayNameToNameMap);
      return mergeSiteWithDefaults(
        partial,
        siteDefaults,
        `sharepoint_list row ${index + 1} (siteId: ${partial.siteId})`,
      );
    });

    this.logger.log(
      `Successfully loaded ${siteConfigs.length} site configurations from SharePoint list`,
    );
    return siteConfigs;
  }

  // We need the mapping because in the API name stays the same, so after rename the old incorrect
  // name will stil be visible in the name field, when the displayName will change.
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
  ): PartialSiteConfig {
    try {
      const fields = item.fields;

      const getFieldValue = (displayName: string) => {
        const internalName = nameMap[displayName];
        const value = internalName ? fields[internalName] : undefined;
        return typeof value === 'string' ? value.trim() : value;
      };

      const siteConfig = {
        siteId: getFieldValue('siteId'),
        syncColumnName: getFieldValue('syncColumnName'),
        ingestionMode: getFieldValue('ingestionMode'),
        scopeId: getFieldValue('uniqueScopeId'),
        // when unset sharepoint list item, maxFilesToIngest is set to 0
        maxFilesToIngest: getFieldValue('maxFilesToIngest') || undefined,
        storeInternally: getFieldValue('storeInternally'),
        syncStatus: getFieldValue('syncStatus'),
        syncMode: getFieldValue('syncMode'),
        permissionsInheritanceMode: getFieldValue('permissionsInheritanceMode'),
        subsitesScan: getFieldValue('subsitesScan'),
      };

      return PartialSiteConfigSchema.parse(siteConfig);
    } catch (error) {
      this.logger.error({
        msg: `Failed to transform list item at index ${index} to PartialSiteConfig`,
        itemId: item.id,
        error: sanitizeError(error),
      });
      throw new Error(
        `Invalid site configuration at row ${index + 1}: ${normalizeError(error).message}`,
      );
    }
  }
}
