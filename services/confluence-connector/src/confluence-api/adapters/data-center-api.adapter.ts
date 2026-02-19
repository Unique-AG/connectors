import { isString } from 'remeda';
import type { ConfluenceApiAdapter } from '../confluence-api-adapter';
import { fetchAllPaginated } from '../confluence-fetch-paginated';
import type { ConfluencePage, ContentType } from '../types/confluence-api.types';

const CHILD_PAGE_LIMIT = 50;

export class DataCenterApiAdapter implements ConfluenceApiAdapter {
  public readonly apiBaseUrl: string;

  public constructor(private readonly baseUrl: string) {
    this.apiBaseUrl = baseUrl;
  }

  public buildSearchUrl(cql: string, limit: number, start: number): string {
    return `${this.baseUrl}/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=metadata.labels,version,space&os_authType=basic&limit=${limit}&start=${start}`;
  }

  public buildGetPageUrl(pageId: string): string {
    return `${this.baseUrl}/rest/api/content/${pageId}?os_authType=basic&expand=body.storage,version,space,metadata.labels`;
  }

  public parseSinglePageResponse(body: unknown): ConfluencePage | null {
    if (body == null || typeof body !== 'object' || !isString((body as ConfluencePage).id)) {
      return null;
    }
    return body as ConfluencePage;
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.baseUrl}/pages/viewpage.action?pageId=${page.id}`;
  }

  public async fetchChildPages(
    parentId: string,
    _contentType: ContentType,
    httpGet: <T>(url: string) => Promise<T>,
  ): Promise<ConfluencePage[]> {
    const url = `${this.baseUrl}/rest/api/content/${parentId}/child/page?os_authType=basic&expand=metadata.labels,version,space&limit=${CHILD_PAGE_LIMIT}`;
    return fetchAllPaginated<ConfluencePage>(url, this.baseUrl, httpGet);
  }
}
