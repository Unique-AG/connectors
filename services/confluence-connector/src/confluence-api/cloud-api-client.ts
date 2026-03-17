import type { Readable } from 'node:stream';
import { chunk, isNullish, uniqueBy } from 'remeda';
import type { ConfluenceAuth } from '../auth/confluence-auth';
import type { ConfluenceConfig } from '../config';
import type { RateLimitedHttpClient } from '../utils/rate-limited-http-client';
import { type ApiClientOptions, ConfluenceApiClient } from './confluence-api-client';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import {
  type ConfluenceAttachment,
  type ConfluencePage,
  confluenceAttachmentV2Schema,
  confluencePageSchema,
  paginatedResponseSchema,
} from './types/confluence-api.types';

const SEARCH_PAGE_SIZE = 100;
const ANCESTOR_BATCH_SIZE = 100;
const ATLASSIAN_API_BASE = 'https://api.atlassian.com/ex/confluence';
const ATTACHMENT_EXPAND =
  ',children.attachment,children.attachment.version,children.attachment.extensions';

type CloudConfig = Extract<ConfluenceConfig, { instanceType: 'cloud' }>;

export class CloudConfluenceApiClient extends ConfluenceApiClient {
  private readonly apiBaseUrl: string;
  private readonly attachmentExpand: string;

  public constructor(
    private readonly config: CloudConfig,
    private readonly confluenceAuth: ConfluenceAuth,
    private readonly httpClient: RateLimitedHttpClient,
    private readonly options: ApiClientOptions = { attachmentsEnabled: false },
  ) {
    super();
    this.apiBaseUrl = `${ATLASSIAN_API_BASE}/${config.cloudId}`;
    this.attachmentExpand = options.attachmentsEnabled ? ATTACHMENT_EXPAND : '';
  }

  public async searchPagesByLabel(): Promise<ConfluencePage[]> {
    const spaceTypeFilter = '(space.type=global OR space.type=collaboration)';
    // Attachments are child content in Confluence and would appear as top-level results here.
    // We exclude them because we already get attachments via the expand=children.attachment parameter.
    const cql = `((label="${this.config.ingestSingleLabel}") OR (label="${this.config.ingestAllLabel}")) AND ${spaceTypeFilter} AND type != attachment`;
    const expand = `metadata.labels,version,space${this.attachmentExpand}`;
    const url = `${this.apiBaseUrl}/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=${expand}&limit=${SEARCH_PAGE_SIZE}&start=0`;

    const pages = await fetchAllPaginated(
      url,
      this.apiBaseUrl,
      (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
      confluencePageSchema,
    );

    // get remaining attachments if more than 25 per page
    if (this.options.attachmentsEnabled) {
      await this.fetchMoreAttachments(pages);
    }

    return pages;
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const expand = 'body.storage,version,space,metadata.labels';
    const url = `${this.apiBaseUrl}/wiki/rest/api/content/search?cql=id%3D${pageId}&expand=${expand}`;
    const raw = await this.makeAuthenticatedRequest(url);

    const response = paginatedResponseSchema(confluencePageSchema).parse(raw);
    return response.results[0] ?? null;
  }

  // V1 CQL `ancestor` returns all descendants at any depth with labels; V2 bulk pages lacks label support.
  public async getDescendantPages(rootIds: string[]): Promise<ConfluencePage[]> {
    if (rootIds.length === 0) {
      return [];
    }

    const batches = chunk(rootIds, ANCESTOR_BATCH_SIZE);
    const results: ConfluencePage[] = [];
    const expand = `metadata.labels,version,space${this.attachmentExpand}`;

    for (const batch of batches) {
      // Attachments are child content in Confluence and would appear as top-level results here.
      // We exclude them because we already get attachments via the expand=children.attachment parameter.
      const cql = `ancestor IN (${batch.join(',')}) AND type != attachment`;
      const url = `${this.apiBaseUrl}/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=${expand}&limit=${SEARCH_PAGE_SIZE}`;

      const pages = await fetchAllPaginated(
        url,
        this.apiBaseUrl,
        (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
        confluencePageSchema,
      );
      results.push(...pages);
    }

    const uniqueResults = uniqueBy(results, (page) => page.id);

    // get the remaining of attachments more than 25 per page
    if (this.options.attachmentsEnabled) {
      await this.fetchMoreAttachments(uniqueResults);
    }

    return uniqueResults;
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.config.baseUrl}/wiki${page._links.webui}`;
  }

  public buildAttachmentWebUrl(
    pageId: string,
    attachmentId: string,
    attachmentTitle: string,
  ): string {
    // Cloud attachment IDs have an 'att' prefix (e.g. 'att360608') but the
    // preview URL uses the numeric part only (e.g. '360608').
    const numericId = attachmentId.replace(/^att/, '');
    const preview = encodeURIComponent(`/${pageId}/${numericId}/${attachmentTitle}`);
    return `${this.config.baseUrl}/wiki/pages/viewpageattachments.action?pageId=${pageId}&preview=${preview}`;
  }

  // Data Center uses downloadPath directly, but Cloud uses the stable REST endpoint instead.
  // The _links.download path does not work via the Atlassian API gateway (returns 500).
  public async getAttachmentDownloadStream(
    attachmentId: string,
    pageId: string,
    _downloadPath: string,
  ): Promise<Readable> {
    const url = `${this.apiBaseUrl}/wiki/rest/api/content/${pageId}/child/attachment/${attachmentId}/download`;
    const token = await this.confluenceAuth.acquireToken();
    return this.httpClient.rateLimitedStreamRequest(url, { Authorization: `Bearer ${token}` });
  }

  // Confluence Cloud inlines up to 25 attachments per page via expand=children.attachment.
  // The v1 pagination endpoint (_links.next) was removed (410 Gone), so pages with more
  // than 25 attachments use the v2 API to fetch the full list.
  protected async fetchMoreAttachments(pages: ConfluencePage[]): Promise<void> {
    for (const page of pages) {
      const attachment = page.children?.attachment;
      if (!attachment) {
        continue;
      }

      const { size, limit } = attachment;
      if (isNullish(size) || isNullish(limit) || size < limit) {
        continue;
      }

      const allAttachments = await this.fetchPageAttachments(page.id);
      attachment.results = allAttachments;
    }
  }

  private async fetchPageAttachments(pageId: string): Promise<ConfluenceAttachment[]> {
    const schema = paginatedResponseSchema(confluenceAttachmentV2Schema);
    const results: ConfluenceAttachment[] = [];
    let url: string | undefined =
      `${this.apiBaseUrl}/wiki/api/v2/pages/${pageId}/attachments?limit=250`;

    while (url) {
      const raw = await this.makeAuthenticatedRequest(url);
      const response = schema.parse(raw);

      for (const item of response.results) {
        results.push({
          id: item.id,
          title: item.title,
          extensions: { mediaType: item.mediaType, fileSize: item.fileSize },
          version: item.version ? { when: item.version.createdAt } : undefined,
          _links: { download: item.downloadLink },
        });
      }

      url = response._links.next ? `${this.apiBaseUrl}${response._links.next}` : undefined;
    }

    return results;
  }

  protected async makeAuthenticatedRequest(url: string): Promise<unknown> {
    const token = await this.confluenceAuth.acquireToken();
    return this.httpClient.rateLimitedRequest(url, { Authorization: `Bearer ${token}` });
  }
}
