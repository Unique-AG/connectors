import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { z } from 'zod';
import { Config } from '../../config';
import { ConfigDiagnosticsService } from '../../config/config-diagnostics.service';
import { SiteConfigSchema } from '../../config/sharepoint.schema';
import { normalizeError, sanitizeError } from '../../utils/normalize-error';
import { createSmeared } from '../../utils/smeared';
import { GraphApiService } from './graph-api.service';
import { ListColumn, ListItem } from './types/sharepoint.types';

type SiteConfig = z.infer<typeof SiteConfigSchema>;

@Injectable()
export class SitesConfigurationService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphApiService: GraphApiService,
    private readonly configService: ConfigService<Config, true>,
    private readonly configDiagnosticsService: ConfigDiagnosticsService,
  ) {}

  /**
   * Loads site configurations from the specified source (config file or SharePoint list).
   */
  public async loadSitesConfiguration(): Promise<SiteConfig[]> {
    const sharepointConfig = this.configService.get('sharepoint', { infer: true });

    if (sharepointConfig.sitesSource === 'config_file') {
      this.logger.log('Loading sites configuration from YAML file');
      this.configDiagnosticsService.logConfig(
        'Loaded SharePoint Sites Configurations',
        sharepointConfig.sites,
      );
      return sharepointConfig.sites;
    }

    this.logger.debug('Loading sites configuration from SharePoint list');
    const sites = await this.fetchSitesFromSharePointList({
      siteId: sharepointConfig.sharepointList.siteId.value,
      listId: sharepointConfig.sharepointList.listId,
    });
    this.configDiagnosticsService.logConfig('Loaded SharePoint Sites Configurations', sites);
    return sites;
  }

  /**
   * Fetch site configurations from a SharePoint list.
   * In order to fetch the sites configuration from a SharePoint list, we need to:
   * 1. Fetch the list items
   * 2. Transform the list items to SiteConfig and validate with Zod
   */
  public async fetchSitesFromSharePointList(sharepointList: {
    siteId: string;
    listId: string;
  }): Promise<SiteConfig[]> {
    const { siteId, listId } = sharepointList;

    this.logger.debug(
      `Fetching sites configuration from site: ${createSmeared(siteId)}, list: ${listId}`,
    );

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
