import { z } from 'zod';
import { ConfluenceApiClient } from './confluence-api-client';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import {
  confluencePageSchema,
  paginatedResponseSchema,
  type ConfluencePage,
  type ContentType,
} from './types/confluence-api.types';

const cloudChildReferenceSchema = z.object({
  id: z.string(),
});

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

  public async getChildPages(
    parentId: string,
    contentType: ContentType,
  ): Promise<ConfluencePage[]> {
    const segment = CONTENT_TYPE_V2_PATH[contentType];
    const url = `${this.baseUrl}/wiki/api/v2/${segment}/${parentId}/direct-children?limit=${CHILDREN_LIMIT}`;
    const childRefs = await fetchAllPaginated(
      url,
      this.baseUrl,
      (requestUrl) => this.makeRateLimitedRequest(requestUrl),
      cloudChildReferenceSchema,
    );
    return this.fetchChildDetails(childRefs);
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.baseUrl}/wiki${page._links.webui}`;
  }

  private async fetchChildDetails(childRefs: z.infer<typeof cloudChildReferenceSchema>[]): Promise<ConfluencePage[]> {
    const pages: ConfluencePage[] = [];
    for (const child of childRefs) {
      const detailUrl = `${this.baseUrl}/wiki/rest/api/content/search?cql=id%3D${child.id}&expand=metadata.labels,version,space`;
      const raw = await this.makeRateLimitedRequest(detailUrl);
      const detail = paginatedResponseSchema(confluencePageSchema).parse(raw);
      const page = detail.results[0];
      if (page) {
        pages.push(page);
      }
    }
    return pages;
  }
}
