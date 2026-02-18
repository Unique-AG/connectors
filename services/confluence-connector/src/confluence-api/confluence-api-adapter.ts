import type { ConfluencePage, ContentType } from './types/confluence-api.types';

export interface ConfluenceApiAdapter {
  buildSearchUrl(cql: string, limit: number, start: number): string;

  buildGetPageUrl(pageId: string, expand: string[]): string;

  parseSinglePageResponse(body: unknown): ConfluencePage | null;

  // Cloud: {baseUrl}/wiki{webui}, DC: {baseUrl}/pages/viewpage.action?pageId={id}.
  // Scope vs path-based ingestion does NOT affect this URL.
  buildPageWebUrl(page: ConfluencePage): string;

  // contentType determines which endpoint to use (Cloud has separate endpoints per type;
  // DC uses a single endpoint regardless of type).
  // httpGet is injected by the client — this IS the client's makeRateLimitedRequest,
  // ensuring all child fetches go through the same per-tenant rate limiter.
  fetchChildPages(
    parentId: string,
    contentType: ContentType,
    httpGet: <T>(url: string) => Promise<T>,
  ): Promise<ConfluencePage[]>;
}
