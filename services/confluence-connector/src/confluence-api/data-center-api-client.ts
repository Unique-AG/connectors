import type { Readable } from 'node:stream';
import { chunk, isNullish, uniqueBy } from 'remeda';
import type { ConfluenceAuth } from '../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../config';
import type { RateLimitedHttpClient } from '../utils/rate-limited-http-client';
import { type ApiClientOptions, ConfluenceApiClient } from './confluence-api-client';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import {
  type ConfluencePage,
  confluenceAttachmentSchema,
  confluencePageSchema,
} from './types/confluence-api.types';

const SEARCH_PAGE_SIZE = 100;
const ANCESTOR_BATCH_SIZE = 100;
const ATTACHMENT_EXPAND =
  ',children.attachment,children.attachment.version,children.attachment.extensions';

export class DataCenterConfluenceApiClient extends ConfluenceApiClient {
  private readonly attachmentExpand: string;

  public constructor(
    private readonly config: ConfluenceConfig,
    private readonly confluenceAuth: ConfluenceAuth,
    private readonly httpClient: RateLimitedHttpClient,
    private readonly options: ApiClientOptions = { attachmentsEnabled: false },
  ) {
    super();
    this.attachmentExpand = options.attachmentsEnabled ? ATTACHMENT_EXPAND : '';
  }

  public async searchPagesByLabel(): Promise<ConfluencePage[]> {
    const spaceTypeFilter = '(space.type=global OR space.type=collaboration)';
    // Attachments are child content in Confluence and would appear as top-level results here.
    // We exclude them because we already get attachments via the expand=children.attachment parameter.
    const cql = `((label="${this.config.ingestSingleLabel}") OR (label="${this.config.ingestAllLabel}")) AND ${spaceTypeFilter} AND type != attachment`;
    const expand = `metadata.labels,version,space${this.attachmentExpand}`;
    const url = `${this.config.baseUrl}/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=${expand}&os_authType=basic&limit=${SEARCH_PAGE_SIZE}&start=0`;

    const pages = await fetchAllPaginated(
      url,
      this.config.baseUrl,
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
    const url = `${this.config.baseUrl}/rest/api/content/${pageId}?os_authType=basic&expand=${expand}`;
    const raw = await this.makeAuthenticatedRequest(url);
    const result = confluencePageSchema.safeParse(raw);
    return result.success ? result.data : null;
  }

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
      const url = `${this.config.baseUrl}/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=${expand}&os_authType=basic&limit=${SEARCH_PAGE_SIZE}`;

      const pages = await fetchAllPaginated(
        url,
        this.config.baseUrl,
        (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
        confluencePageSchema,
      );
      results.push(...pages);
    }

    const uniqueResults = uniqueBy(results, (page) => page.id);

    // get remaining attachments if more than 25 per page
    if (this.options.attachmentsEnabled) {
      await this.fetchMoreAttachments(uniqueResults);
    }

    return uniqueResults;
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.config.baseUrl}/pages/viewpage.action?pageId=${page.id}`;
  }

  public async getAttachmentDownloadStream(
    _attachmentId: string,
    _pageId: string,
    downloadPath: string,
  ): Promise<Readable> {
    const url = `${this.config.baseUrl}${downloadPath}`;
    const token = await this.confluenceAuth.acquireToken();
    return this.httpClient.rateLimitedStreamRequest(url, { Authorization: `Bearer ${token}` });
  }

  // Data Center does not have a v2 REST API, so we follow the v1 _links.next
  // pagination links to fetch remaining attachments beyond the initial 25.
  protected async fetchMoreAttachments(pages: ConfluencePage[]): Promise<void> {
    for (const page of pages) {
      const attachment = page.children?.attachment;
      if (!attachment) {
        continue;
      }

      const { size, limit, _links } = attachment;
      if (isNullish(size) || isNullish(limit) || size < limit || !_links?.next) {
        continue;
      }

      const attachments = await fetchAllPaginated(
        `${this.config.baseUrl}${_links.next}`,
        this.config.baseUrl,
        (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
        confluenceAttachmentSchema,
      );
      attachment.results.push(...attachments);
    }
  }

  protected async makeAuthenticatedRequest(url: string): Promise<unknown> {
    const token = await this.confluenceAuth.acquireToken();
    return this.httpClient.rateLimitedRequest(url, { Authorization: `Bearer ${token}` });
  }
}
