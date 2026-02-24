import type { ConfluenceAuth } from '../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../config';
import type { RateLimitedHttpClient } from '../utils/rate-limited-http-client';
import { ConfluenceApiClient } from './confluence-api-client';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import {
  type ConfluencePage,
  confluencePageSchema,
  paginatedResponseSchema,
} from './types/confluence-api.types';

const SEARCH_PAGE_SIZE = 25;
const ATLASSIAN_API_BASE = 'https://api.atlassian.com/ex/confluence';

type CloudConfig = Extract<ConfluenceConfig, { instanceType: 'cloud' }>;

export class CloudConfluenceApiClient extends ConfluenceApiClient {
  private readonly apiBaseUrl: string;

  public constructor(
    private readonly config: CloudConfig,
    private readonly confluenceAuth: ConfluenceAuth,
    private readonly httpClient: RateLimitedHttpClient,
  ) {
    super();
    this.apiBaseUrl = `${ATLASSIAN_API_BASE}/${config.cloudId}`;
  }

  public async searchPagesByLabel(): Promise<ConfluencePage[]> {
    const spaceTypeFilter = '(space.type=global OR space.type=collaboration)';
    const cql = `((label="${this.config.ingestSingleLabel}") OR (label="${this.config.ingestAllLabel}")) AND ${spaceTypeFilter} AND type != attachment`;
    const url = `${this.apiBaseUrl}/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=metadata.labels,version,space&limit=${SEARCH_PAGE_SIZE}&start=0`;

    return fetchAllPaginated(
      url,
      this.apiBaseUrl,
      (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
      confluencePageSchema,
    );
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const url = `${this.apiBaseUrl}/wiki/rest/api/content/search?cql=id%3D${pageId}&expand=body.storage,version,space,metadata.labels`;
    const raw = await this.makeAuthenticatedRequest(url);
    const response = paginatedResponseSchema(confluencePageSchema).parse(raw);
    return response.results[0] ?? null;
  }

  // V1 CQL `ancestor` returns all descendants at any depth with labels; V2 bulk pages lacks label support.
  public async getDescendantPages(rootIds: string[]): Promise<ConfluencePage[]> {
    if (rootIds.length === 0) return [];

    const cql = `ancestor IN (${rootIds.join(',')}) AND type != attachment`;
    const url = `${this.apiBaseUrl}/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=metadata.labels,version,space&limit=${SEARCH_PAGE_SIZE}`;

    return fetchAllPaginated(
      url,
      this.apiBaseUrl,
      (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
      confluencePageSchema,
    );
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.config.baseUrl}/wiki${page._links.webui}`;
  }

  private async makeAuthenticatedRequest(url: string): Promise<unknown> {
    const token = await this.confluenceAuth.acquireToken();
    return this.httpClient.rateLimitedRequest(url, { Authorization: `Bearer ${token}` });
  }
}
