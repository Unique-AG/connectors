import { ConfluenceApiClient } from './confluence-api-client';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import { confluencePageSchema, type ConfluencePage, type ContentType } from './types/confluence-api.types';

const CHILD_PAGE_LIMIT = 50;
const SEARCH_PAGE_SIZE = 25;

export class DataCenterConfluenceApiClient extends ConfluenceApiClient {
  public async searchPagesByLabel(): Promise<ConfluencePage[]> {
    const spaceTypeFilter = 'space.type=global';
    const cql = `((label="${this.config.ingestSingleLabel}") OR (label="${this.config.ingestAllLabel}")) AND ${spaceTypeFilter} AND type != attachment`;
    const url = `${this.baseUrl}/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=metadata.labels,version,space&os_authType=basic&limit=${SEARCH_PAGE_SIZE}&start=0`;

    return fetchAllPaginated(url, this.baseUrl, (requestUrl) =>
      this.makeRateLimitedRequest(requestUrl),
      confluencePageSchema,
    );
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const url = `${this.baseUrl}/rest/api/content/${pageId}?os_authType=basic&expand=body.storage,version,space,metadata.labels`;
    const raw = await this.makeRateLimitedRequest(url);
    const result = confluencePageSchema.safeParse(raw);
    return result.success ? result.data : null;
  }

  public async getChildPages(
    parentId: string,
    _contentType: ContentType,
  ): Promise<ConfluencePage[]> {
    const url = `${this.baseUrl}/rest/api/content/${parentId}/child/page?os_authType=basic&expand=metadata.labels,version,space&limit=${CHILD_PAGE_LIMIT}`;

    return fetchAllPaginated(url, this.baseUrl, (requestUrl) =>
      this.makeRateLimitedRequest(requestUrl),
      confluencePageSchema,
    );
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.baseUrl}/pages/viewpage.action?pageId=${page.id}`;
  }
}
