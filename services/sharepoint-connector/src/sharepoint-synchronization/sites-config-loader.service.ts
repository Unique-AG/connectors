import assert from 'node:assert';
import type { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import type { SharepointConfig, SiteConfig } from '../config/sharepoint.schema';
import { SiteConfigSchema } from '../config/sharepoint.schema';
import { GRAPH_API_PAGE_SIZE } from '../constants/defaults.constants';
import { GraphClientFactory } from '../microsoft-apis/graph/graph-client.factory';
import type { GraphApiResponse, ListItem } from '../microsoft-apis/graph/types/sharepoint.types';
import { redact, shouldConcealLogs, smear } from '../utils/logging.util';
import { sanitizeError } from '../utils/normalize-error';

interface ParsedListUrl {
  hostname: string;
  relativePath: string;
  listName: string;
}

@Injectable()
export class SitesConfigLoaderService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly graphClient: Client;
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.graphClient = this.graphClientFactory.createClient();
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

  /**
   * Load sites configuration based on the configured source.
   * For 'config_file' source, returns the sites array from config.
   * For 'sharepoint_list' source, fetches sites from SharePoint list URL.
   */
  public async loadSites(config: SharepointConfig): Promise<SiteConfig[]> {
    if (config.sitesSource === 'config_file') {
      this.logger.log('Loading sites configuration from static YAML');
      return config.sites;
    }

    this.logger.debug('Loading sites configuration from SharePoint list');
    return this.fetchFromSharePointList(config.sharepointListUrl);
  }

  /**
   * Fetch site configurations from a SharePoint list.
   * In order to fetch the sites configuration from a SharePoint list, we need to:
   * 1. Parse the list URL to get the hostname, relative path, and list name
   * 2. Get the site ID by URL
   * 3. Get the list ID by name
   * 4. Fetch the list items
   * 5. Transform the list items to SiteConfig and validate with Zod
   * Returns the SiteConfig array
   */
  private async fetchFromSharePointList(listUrl: string): Promise<SiteConfig[]> {
    this.logger.log(`Fetching sites configuration from: ${listUrl}`);

    const parsedListUrl = this.parseListUrl(listUrl);
    this.logger.debug(
      `Parsed URL - hostname: ${parsedListUrl.hostname}, path: ${this.shouldConcealLogs ? redact(parsedListUrl.relativePath) : parsedListUrl.relativePath}, list: ${parsedListUrl.listName}`,
    );

    const siteId = await this.getSiteIdByUrl(parsedListUrl.hostname, parsedListUrl.relativePath);
    const logSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
    this.logger.log(`Resolved site ID: ${logSiteId}`);

    const listId = await this.getListIdByName(siteId, parsedListUrl.listName);
    this.logger.log(`Resolved list ID: ${listId}`);

    const listItems = await this.getListItems(siteId, listId);
    this.logger.log(`Fetched ${listItems.length} items from SharePoint list`);

    const siteConfigs = listItems.map((item, index) =>
      this.transformListItemToSiteConfig(item, index),
    );

    this.logger.log(
      `Successfully loaded ${siteConfigs.length} site configurations from SharePoint list`,
    );
    return siteConfigs;
  }

  /**
   * Parse SharePoint list URL to extract components.
   * Example: https://uniqueapp.sharepoint.com/sites/QA/Lists/Sharepoint%20Sites%20to%20Sync/AllItems.aspx
   * Returns: { hostname: 'uniqueapp.sharepoint.com', relativePath: '/sites/QA', listName: 'Sharepoint Sites to Sync' }
   */
  private parseListUrl(url: string): ParsedListUrl {
    try {
      const urlObj = new URL(url);
      const hostname = urlObj.hostname;

      const pathParts = urlObj.pathname.split('/').filter(Boolean);
      const listsIndex = pathParts.findIndex((part) => part.toLowerCase() === 'lists');

      assert.ok(
        listsIndex > 0 && listsIndex < pathParts.length - 1,
        'Invalid SharePoint list URL format - missing "Lists" segment',
      );

      const listNameSegment = pathParts[listsIndex + 1];
      assert.ok(listNameSegment, 'List name not found in URL');
      const listName = decodeURIComponent(listNameSegment);

      // Build relative path: everything before /Lists/
      const relativePath = `/${pathParts.slice(0, listsIndex).join('/')}`;
      return { hostname, relativePath, listName };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to parse SharePoint list URL',
        url,
        error: sanitizeError(error),
      });
      throw new Error(`Invalid SharePoint list URL: ${url}`);
    }
  }

  /**
   * Get site ID by URL using Graph API.
   * Uses format: /sites/{hostname}:{relative-path}
   * The API returns a composite ID in format: {hostname},{siteId},{webId}
   * We extract and return only the siteId portion.
   */
  private async getSiteIdByUrl(hostname: string, relativePath: string): Promise<string> {
    try {
      const siteIdentifier = `${hostname}:${relativePath}`;
      const response = await this.graphClient.api(`/sites/${siteIdentifier}`).select('id').get();

      assert.ok(response?.id, 'Site ID not found in response');

      // The response.id is in format: "<hostname>,<siteId>,<webId>" we need to extract only siteId
      const idParts = response.id.split(',');
      if (idParts.length === 3) {
        const siteId = idParts[1];
        this.logger.debug(`Extracted site ID: ${this.shouldConcealLogs ? smear(siteId) : siteId}`);
        return siteId;
      }

      // if format is unexpected, return value from response
      this.logger.warn(
        `Unexpected site ID format: ${this.shouldConcealLogs ? smear(response.id) : response.id}`,
      );
      return response.id;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to get site ID by URL',
        hostname,
        relativePath,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  // fetch all lists with pagination since $filter is not supported on name/displayName and we need to filter client-side
  private async getListIdByName(siteId: string, listName: string): Promise<string> {
    try {
      const allLists = await this.paginateGraphApiRequest<{
        id: string;
        name: string;
        displayName: string;
      }>(`/sites/${siteId}/lists`, (url) =>
        this.graphClient.api(url).select('id,name').top(GRAPH_API_PAGE_SIZE).get(),
      );

      const matchingList = allLists.find((list) => list.name === listName);

      assert.ok(matchingList, `List "${listName}" not found in site`);

      this.logger.debug({
        msg: 'Found list',
        listId: matchingList.id,
        listName: matchingList.name,
        displayName: matchingList.displayName,
      });

      return matchingList.id;
    } catch (error) {
      const logSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
      this.logger.error({
        msg: 'Failed to get list ID by name',
        siteId: logSiteId,
        listName,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  private async getListItems(siteId: string, listId: string): Promise<ListItem[]> {
    try {
      return await this.paginateGraphApiRequest<ListItem>(
        `/sites/${siteId}/lists/${listId}/items`,
        (url) => this.graphClient.api(url).expand('fields').top(GRAPH_API_PAGE_SIZE).get(),
      );
    } catch (error) {
      const logSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
      this.logger.error({
        msg: 'Failed to fetch list items',
        siteId: logSiteId,
        listId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  private transformListItemToSiteConfig(item: ListItem, index: number): SiteConfig {
    try {
      const fields = item.fields;

      const siteConfig = {
        siteId: fields.syncSiteId,
        syncColumnName: fields.syncColumnName,
        ingestionMode: fields.ingestionMode,
        scopeId: fields.uniqueScopeId,
        maxFilesToIngest: fields.maxFilesToIngest,
        storeInternally: fields.storeInternally,
        syncStatus: fields.syncStatus,
        syncMode: fields.syncMode,
        permissionsInheritanceMode: fields.permissionsInheritanceMode,
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

  private async paginateGraphApiRequest<T>(
    initialUrl: string,
    requestBuilder: (url: string) => Promise<GraphApiResponse<T>>,
  ): Promise<T[]> {
    const allItems: T[] = [];
    let nextPageUrl: string | null = initialUrl;

    while (nextPageUrl !== null) {
      const response: GraphApiResponse<T> = await requestBuilder(nextPageUrl);

      if (response.value) {
        allItems.push(...response.value);
      }

      nextPageUrl = response['@odata.nextLink'] || null;
    }

    return allItems;
  }
}
