import { chunk } from 'remeda';
import type { ConfluenceAuth } from '../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../config';
import type { RateLimitedHttpClient } from '../utils/rate-limited-http-client';
import { ConfluenceApiClient } from './confluence-api-client';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import { type ConfluencePage, confluencePageSchema } from './types/confluence-api.types';

const SEARCH_PAGE_SIZE = 100;
const ANCESTOR_BATCH_SIZE = 100;

export class DataCenterConfluenceApiClient extends ConfluenceApiClient {
  public constructor(
    private readonly config: ConfluenceConfig,
    private readonly confluenceAuth: ConfluenceAuth,
    private readonly httpClient: RateLimitedHttpClient,
  ) {
    super();
  }

  public async searchPagesByLabel(): Promise<ConfluencePage[]> {
    const spaceTypeFilter = 'space.type=global';
    const cql = `((label="${this.config.ingestSingleLabel}") OR (label="${this.config.ingestAllLabel}")) AND ${spaceTypeFilter} AND type != attachment`;
    const url = `${this.config.baseUrl}/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=metadata.labels,version,space&os_authType=basic&limit=${SEARCH_PAGE_SIZE}&start=0`;

    return fetchAllPaginated(
      url,
      this.config.baseUrl,
      (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
      confluencePageSchema,
    );
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const url = `${this.config.baseUrl}/rest/api/content/${pageId}?os_authType=basic&expand=body.storage,version,space,metadata.labels`;
    const raw = await this.makeAuthenticatedRequest(url);
    const result = confluencePageSchema.safeParse(raw);
    return result.success ? result.data : null;
  }

  public async getDescendantPages(rootIds: string[]): Promise<ConfluencePage[]> {
    if (rootIds.length === 0) return [];

    const batches = chunk(rootIds, ANCESTOR_BATCH_SIZE);
    const results: ConfluencePage[] = [];

    for (const batch of batches) {
      const cql = `ancestor IN (${batch.join(',')}) AND type != attachment`;
      const url = `${this.config.baseUrl}/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=metadata.labels,version,space&os_authType=basic&limit=${SEARCH_PAGE_SIZE}`;

      const pages = await fetchAllPaginated(
        url,
        this.config.baseUrl,
        (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
        confluencePageSchema,
      );
      results.push(...pages);
    }

    return results;
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.config.baseUrl}/pages/viewpage.action?pageId=${page.id}`;
  }

  private async makeAuthenticatedRequest(url: string): Promise<unknown> {
    const token = await this.confluenceAuth.acquireToken();
    return this.httpClient.rateLimitedRequest(url, { Authorization: `Bearer ${token}` });
  }
}
