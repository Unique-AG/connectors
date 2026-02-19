import { isArray, isPlainObject, isString } from 'remeda';
import type { ConfluenceApiAdapter } from '../confluence-api-adapter';
import { fetchAllPaginated } from '../confluence-fetch-paginated';
import type { ConfluencePage, ContentType, PaginatedResponse } from '../types/confluence-api.types';

interface CloudChildReference {
  id: string;
}

const CHILDREN_LIMIT = 250;

const CONTENT_TYPE_V2_PATH: Record<ContentType, string> = {
  page: 'pages',
  folder: 'folders',
  database: 'databases',
};

export class CloudApiAdapter implements ConfluenceApiAdapter {
  public readonly apiBaseUrl: string;

  public constructor(
    apiBaseUrl: string,
    private readonly siteBaseUrl: string,
  ) {
    this.apiBaseUrl = apiBaseUrl;
  }

  public buildSearchUrl(cql: string, limit: number, start: number): string {
    return `${this.apiBaseUrl}/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=metadata.labels,version,space&limit=${limit}&start=${start}`;
  }

  public buildGetPageUrl(pageId: string): string {
    return `${this.apiBaseUrl}/wiki/rest/api/content/search?cql=id%3D${pageId}&expand=body.storage,version,space,metadata.labels`;
  }

  public parseSinglePageResponse(body: unknown): ConfluencePage | null {
    if (!isPlainObject(body) || !isArray(body.results)) {
      return null;
    }
    const first = body.results[0];
    if (!isPlainObject(first) || !isString(first.id)) {
      return null;
    }
    return first as unknown as ConfluencePage;
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.siteBaseUrl}/wiki${page._links.webui}`;
  }

  public async fetchChildPages(
    parentId: string,
    contentType: ContentType,
    httpGet: <T>(url: string) => Promise<T>,
  ): Promise<ConfluencePage[]> {
    const segment = CONTENT_TYPE_V2_PATH[contentType];
    const url = `${this.apiBaseUrl}/wiki/api/v2/${segment}/${parentId}/direct-children?limit=${CHILDREN_LIMIT}`;
    const childRefs = await fetchAllPaginated<CloudChildReference>(url, this.apiBaseUrl, httpGet);
    return await this.fetchChildDetails(childRefs, httpGet);
  }

  private async fetchChildDetails(
    childRefs: CloudChildReference[],
    httpGet: <T>(url: string) => Promise<T>,
  ): Promise<ConfluencePage[]> {
    const pages: ConfluencePage[] = [];
    for (const child of childRefs) {
      const detailUrl = `${this.apiBaseUrl}/wiki/rest/api/content/search?cql=id%3D${child.id}&expand=metadata.labels,version,space`;
      const detail = await httpGet<PaginatedResponse<ConfluencePage>>(detailUrl);
      const page = detail.results[0];
      if (page) {
        pages.push(page);
      }
    }
    return pages;
  }
}
