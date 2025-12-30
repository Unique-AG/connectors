import assert from 'node:assert';
import type { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import type { SharepointConfig, SiteConfig } from '../config/sharepoint.schema';
import { SiteConfigSchema } from '../config/sharepoint.schema';
import { GRAPH_API_PAGE_SIZE } from '../constants/defaults.constants';
import { GraphClientFactory } from '../microsoft-apis/graph/graph-client.factory';
import type { GraphApiResponse, ListItem } from '../microsoft-apis/graph/types/sharepoint.types';
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

  public constructor(private readonly graphClientFactory: GraphClientFactory) {
    this.graphClient = this.graphClientFactory.createClient();
  }

  /**
   * Load sites configuration based on the configured source.
   * For 'configFile' source, returns the sites array from config.
   * For 'sharePointList' source, fetches sites from SharePoint list URL.
   */
  public async loadSites(config: SharepointConfig): Promise<SiteConfig[]> {
    if (config.sitesSource === 'configFile') {
      this.logger.log('Loading sites configuration from static YAML');
      return config.sites;
    }

    // sitesSource === 'sharePointList'
    this.logger.log('Loading sites configuration from SharePoint list');
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
   * 6. Return the SiteConfig array
   */
  private async fetchFromSharePointList(listUrl: string): Promise<SiteConfig[]> {
    this.logger.log(`Fetching sites configuration from: ${listUrl}`);

    // Parse the list URL
    const parsed = this.parseListUrl(listUrl);
    this.logger.debug(
      `Parsed URL - hostname: ${parsed.hostname}, path: ${parsed.relativePath}, list: ${parsed.listName}`,
    );

    // Get site by URL
    const siteId = await this.getSiteIdByUrl(parsed.hostname, parsed.relativePath);
    this.logger.log(`Resolved site ID: ${siteId}`);

    // Get list by name
    const listId = await this.getListIdByName(siteId, parsed.listName);
    this.logger.log(`Resolved list ID: ${listId}`);

    // Fetch list items
    const listItems = await this.getListItems(siteId, listId);
    this.logger.log(`Fetched ${listItems.length} items from SharePoint list`);

    // Transform and validate
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

      // Extract path components
      const pathParts = urlObj.pathname.split('/').filter(Boolean);

      // Find the "Lists" segment
      const listsIndex = pathParts.findIndex((part) => part.toLowerCase() === 'lists');

      assert.ok(
        listsIndex > 0 && listsIndex < pathParts.length - 1,
        'Invalid SharePoint list URL format - missing "Lists" segment',
      );

      // Build relative path (everything before /Lists/)
      const relativePath = `/${pathParts.slice(0, listsIndex).join('/')}`;

      // List name is the segment after "Lists" (URL decoded)
      const listNameSegment = pathParts[listsIndex + 1];
      assert.ok(listNameSegment, 'List name not found in URL');
      const listName = decodeURIComponent(listNameSegment);

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
   */
  private async getSiteIdByUrl(hostname: string, relativePath: string): Promise<string> {
    try {
      const siteIdentifier = `${hostname}:${relativePath}`;
      const response = await this.graphClient.api(`/sites/${siteIdentifier}`).select('id').get();

      assert.ok(response?.id, 'Site ID not found in response');
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

  /**
   * Get list ID by display name.
   */
  private async getListIdByName(siteId: string, listName: string): Promise<string> {
    try {
      const response = await this.graphClient
        .api(`/sites/${siteId}/lists`)
        .filter(`displayName eq '${listName.replace(/'/g, "''")}'`)
        .select('id,displayName')
        .get();

      assert.ok(response?.value?.length > 0, `List "${listName}" not found in site`);
      return response.value[0].id;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to get list ID by name',
        siteId,
        listName,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  /**
   * Fetch all list items with pagination.
   */
  private async getListItems(siteId: string, listId: string): Promise<ListItem[]> {
    try {
      return await this.paginateGraphApiRequest<ListItem>(
        `/sites/${siteId}/lists/${listId}/items`,
        (url) => this.graphClient.api(url).expand('fields').top(GRAPH_API_PAGE_SIZE).get(),
      );
    } catch (error) {
      this.logger.error({
        msg: 'Failed to fetch list items',
        siteId,
        listId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  /**
   * Transform SharePoint list item to SiteConfig and validate with Zod.
   */
  private transformListItemToSiteConfig(item: ListItem, index: number): SiteConfig {
    try {
      const fields = item.fields;

      // Build the site config object from list item fields
      const siteConfig = {
        siteId: fields.siteId,
        syncColumnName: fields.syncColumnName,
        ingestionMode: fields.ingestionMode,
        scopeId: fields.scopeId,
        maxFilesToIngest: fields.maxFilesToIngest,
        storeInternally: fields.storeInternally,
        syncStatus: fields.syncStatus,
        syncMode: fields.syncMode,
      };

      // Validate with Zod schema
      const validated = SiteConfigSchema.parse(siteConfig);
      return validated;
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

  /**
   * Paginate through Graph API responses.
   */
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
