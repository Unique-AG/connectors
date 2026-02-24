import { isArray, isPlainObject, isString } from 'remeda';
import { ConfluenceApiClient } from './confluence-api-client';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import type { ConfluencePage, ContentType, PaginatedResponse } from './types/confluence-api.types';

interface CloudChildReference {
  id: string;
}

const SEARCH_PAGE_SIZE = 25;
const CHILDREN_LIMIT = 250;

const CONTENT_TYPE_V2_PATH: Record<ContentType, string> = {
  page: 'pages',
  folder: 'folders',
  database: 'databases',
};

export class CloudConfluenceApiClient extends ConfluenceApiClient {
  public async searchPagesByLabel(): Promise<ConfluencePage[]> {
    const spaceTypeFilter = '(space.type=global OR space.type=collaboration)';
    const cql = `((label="${this.config.ingestSingleLabel}") OR (label="${this.config.ingestAllLabel}")) AND ${spaceTypeFilter} AND type != attachment`;
    const url = `${this.baseUrl}/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=metadata.labels,version,space&limit=${SEARCH_PAGE_SIZE}&start=0`;

    return fetchAllPaginated<ConfluencePage>(url, this.baseUrl, (requestUrl) =>
      this.makeRateLimitedRequest(requestUrl),
    );
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const url = `${this.baseUrl}/wiki/rest/api/content/search?cql=id%3D${pageId}&expand=body.storage,version,space,metadata.labels`;
    const body: unknown = await this.makeRateLimitedRequest(url);

    if (!isPlainObject(body) || !isArray(body.results)) {
      return null;
    }
    const first = body.results[0];
    if (!isPlainObject(first) || !isString(first.id)) {
      return null;
    }
    return first as unknown as ConfluencePage;
  }

  public async getChildPages(
    parentId: string,
    contentType: ContentType,
  ): Promise<ConfluencePage[]> {
    const segment = CONTENT_TYPE_V2_PATH[contentType];
    const url = `${this.baseUrl}/wiki/api/v2/${segment}/${parentId}/direct-children?limit=${CHILDREN_LIMIT}`;
    const childRefs = await fetchAllPaginated<CloudChildReference>(
      url,
      this.baseUrl,
      (requestUrl) => this.makeRateLimitedRequest(requestUrl),
    );
    return this.fetchChildDetails(childRefs);
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.baseUrl}/wiki${page._links.webui}`;
  }

  private async fetchChildDetails(childRefs: CloudChildReference[]): Promise<ConfluencePage[]> {
    const pages: ConfluencePage[] = [];
    for (const child of childRefs) {
      const detailUrl = `${this.baseUrl}/wiki/rest/api/content/search?cql=id%3D${child.id}&expand=metadata.labels,version,space`;
      const detail =
        await this.makeRateLimitedRequest<PaginatedResponse<ConfluencePage>>(detailUrl);
      const page = detail.results[0];
      if (page) {
        pages.push(page);
      }
    }
    return pages;
  }
}
