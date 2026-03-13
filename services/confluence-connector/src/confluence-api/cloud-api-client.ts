import type { Readable } from 'node:stream';
import { chunk, uniqueBy } from 'remeda';
import type { ConfluenceAuth } from '../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../config';
import type { RateLimitedHttpClient } from '../utils/rate-limited-http-client';
import { type ApiClientOptions, ConfluenceApiClient } from './confluence-api-client';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import {
  type ConfluencePage,
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
  protected readonly paginationBaseUrl: string;
  private readonly attachmentExpand: string;

  public constructor(
    private readonly config: CloudConfig,
    private readonly confluenceAuth: ConfluenceAuth,
    private readonly httpClient: RateLimitedHttpClient,
    private readonly options: ApiClientOptions = { attachmentsEnabled: false },
  ) {
    super();
    this.paginationBaseUrl = `${ATLASSIAN_API_BASE}/${config.cloudId}`;
    this.attachmentExpand = options.attachmentsEnabled ? ATTACHMENT_EXPAND : '';
  }

  public async searchPagesByLabel(): Promise<ConfluencePage[]> {
    const spaceTypeFilter = '(space.type=global OR space.type=collaboration)';
    // Attachments are child content in Confluence and would appear as top-level results here.
    // We exclude them because we already get attachments via the expand=children.attachment parameter.
    const cql = `((label="${this.config.ingestSingleLabel}") OR (label="${this.config.ingestAllLabel}")) AND ${spaceTypeFilter} AND type != attachment`;
    const expand = `metadata.labels,version,space${this.attachmentExpand}`;
    const url = `${this.paginationBaseUrl}/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=${expand}&limit=${SEARCH_PAGE_SIZE}&start=0`;

    const pages = await fetchAllPaginated(
      url,
      this.paginationBaseUrl,
      (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
      confluencePageSchema,
    );

    // get attachments if they are more than 25 attachments per page
    if (this.options.attachmentsEnabled) {
      await this.completePaginatedAttachments(pages);
    }

    return pages;
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const expand = 'body.storage,version,space,metadata.labels';
    const url = `${this.paginationBaseUrl}/wiki/rest/api/content/search?cql=id%3D${pageId}&expand=${expand}`;
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
      const url = `${this.paginationBaseUrl}/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=${expand}&limit=${SEARCH_PAGE_SIZE}`;

      const pages = await fetchAllPaginated(
        url,
        this.paginationBaseUrl,
        (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
        confluencePageSchema,
      );
      results.push(...pages);
    }

    const uniqueResults = uniqueBy(results, (page) => page.id);

    // get the remaining of attachments if there are more than 25 per page
    if (this.options.attachmentsEnabled) {
      await this.completePaginatedAttachments(uniqueResults);
    }

    return uniqueResults;
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.config.baseUrl}/wiki${page._links.webui}`;
  }

  public async getAttachmentDownloadStream(
    attachmentId: string,
    pageId: string,
    _downloadPath: string,
  ): Promise<Readable> {
    const url = `${this.paginationBaseUrl}/wiki/rest/api/content/${pageId}/child/attachment/${attachmentId}/download`;
    const token = await this.confluenceAuth.acquireToken();
    return this.httpClient.rateLimitedStreamRequest(url, { Authorization: `Bearer ${token}` });
  }

  protected async makeAuthenticatedRequest(url: string): Promise<unknown> {
    const token = await this.confluenceAuth.acquireToken();
    return this.httpClient.rateLimitedRequest(url, { Authorization: `Bearer ${token}` });
  }
}
