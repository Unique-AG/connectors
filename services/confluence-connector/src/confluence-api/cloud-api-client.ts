import { ConfluenceApiClient } from './confluence-api-client';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import {
  confluencePageSchema,
  paginatedResponseSchema,
  type ConfluencePage,
} from './types/confluence-api.types';

const SEARCH_PAGE_SIZE = 25;

export class CloudConfluenceApiClient extends ConfluenceApiClient {
  public async searchPagesByLabel(): Promise<ConfluencePage[]> {
    const spaceTypeFilter = '(space.type=global OR space.type=collaboration)';
    const cql = `((label="${this.config.ingestSingleLabel}") OR (label="${this.config.ingestAllLabel}")) AND ${spaceTypeFilter} AND type != attachment`;
    const url = `${this.baseUrl}/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=metadata.labels,version,space&limit=${SEARCH_PAGE_SIZE}&start=0`;

    return fetchAllPaginated(url, this.baseUrl, (requestUrl) =>
      this.makeRateLimitedRequest(requestUrl),
      confluencePageSchema,
    );
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const url = `${this.baseUrl}/wiki/rest/api/content/search?cql=id%3D${pageId}&expand=body.storage,version,space,metadata.labels`;
    const raw = await this.makeRateLimitedRequest(url);
    const response = paginatedResponseSchema(confluencePageSchema).parse(raw);
    return response.results[0] ?? null;
  }

  // Uses V1 CQL `ancestor` instead of V2 GET /pages?id=... because the V2 bulk pages
  // endpoint does not return labels (include-labels is not supported). Labels are required
  // by the page scanner for ingestAllLabel checks. The only V2 labels endpoint is per-page
  // (GET /pages/{id}/labels), which would recreate the N+1 problem.
  public async getDescendantPages(rootIds: string[]): Promise<ConfluencePage[]> {
    if (rootIds.length === 0) return [];

    const ancestorClause = rootIds.length === 1
      ? `ancestor=${rootIds[0]}`
      : `ancestor IN (${rootIds.join(',')})`;
    const cql = `${ancestorClause} AND type != attachment`;
    const url = `${this.baseUrl}/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=metadata.labels,version,space&limit=${SEARCH_PAGE_SIZE}`;

    return fetchAllPaginated(url, this.baseUrl, (requestUrl) =>
      this.makeRateLimitedRequest(requestUrl),
      confluencePageSchema,
    );
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.baseUrl}/wiki${page._links.webui}`;
  }
}
