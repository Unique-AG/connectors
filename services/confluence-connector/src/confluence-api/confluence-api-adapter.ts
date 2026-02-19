import type { ConfluencePage, ContentType } from './types/confluence-api.types';

export interface ConfluenceApiAdapter {
  readonly apiBaseUrl: string;
  buildSearchUrl(cql: string, limit: number, start: number): string;
  buildGetPageUrl(pageId: string): string;
  parseSinglePageResponse(body: unknown): ConfluencePage | null;
  buildPageWebUrl(page: ConfluencePage): string;
  // httpGet is the client's rate-limited request function, injected so adapters stay HTTP-free
  fetchChildPages(
    parentId: string,
    contentType: ContentType,
    httpGet: <T>(url: string) => Promise<T>,
  ): Promise<ConfluencePage[]>;
}
