import { chunk, uniqueBy } from 'remeda';
import type { ConfluenceAuth } from '../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../config';
import type { RateLimitedHttpClient } from '../utils/rate-limited-http-client';
import { type ApiClientOptions, ConfluenceApiClient } from './confluence-api-client';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import {
  type ConfluenceAttachment,
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
    const spaceTypeFilter = 'space.type=global';
    const cql = `((label="${this.config.ingestSingleLabel}") OR (label="${this.config.ingestAllLabel}")) AND ${spaceTypeFilter} AND type != attachment`;
    const expand = `metadata.labels,version,space${this.attachmentExpand}`;
    const url = `${this.config.baseUrl}/rest/api/content/search?cql=${encodeURIComponent(cql)}&expand=${expand}&os_authType=basic&limit=${SEARCH_PAGE_SIZE}&start=0`;

    const pages = await fetchAllPaginated(
      url,
      this.config.baseUrl,
      (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
      confluencePageSchema,
    );

    if (this.options.attachmentsEnabled) {
      await this.fetchRemainingAttachments(pages);
    }

    return pages;
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const expand = `body.storage,version,space,metadata.labels${this.attachmentExpand}`;
    const url = `${this.config.baseUrl}/rest/api/content/${pageId}?os_authType=basic&expand=${expand}`;
    const raw = await this.makeAuthenticatedRequest(url);
    const result = confluencePageSchema.safeParse(raw);
    const page = result.success ? result.data : null;

    if (page && this.options.attachmentsEnabled) {
      await this.fetchRemainingAttachments([page]);
    }

    return page;
  }

  public async getDescendantPages(rootIds: string[]): Promise<ConfluencePage[]> {
    if (rootIds.length === 0) {
      return [];
    }

    const batches = chunk(rootIds, ANCESTOR_BATCH_SIZE);
    const results: ConfluencePage[] = [];
    const expand = `metadata.labels,version,space${this.attachmentExpand}`;

    for (const batch of batches) {
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

    if (this.options.attachmentsEnabled) {
      await this.fetchRemainingAttachments(uniqueResults);
    }

    return uniqueResults;
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.config.baseUrl}/pages/viewpage.action?pageId=${page.id}`;
  }

  private async makeAuthenticatedRequest(url: string): Promise<unknown> {
    const token = await this.confluenceAuth.acquireToken();
    return this.httpClient.rateLimitedRequest(url, { Authorization: `Bearer ${token}` });
  }

  private async fetchRemainingAttachments(pages: ConfluencePage[]): Promise<void> {
    for (const page of pages) {
      const attachment = page.children?.attachment;
      if (!attachment) {
        continue;
      }

      const { size, limit, _links } = attachment;
      if (size === undefined || limit === undefined || size < limit || !_links?.next) {
        continue;
      }

      const remaining = await this.fetchPaginatedAttachments(_links.next);
      attachment.results.push(...remaining);
    }
  }

  private async fetchPaginatedAttachments(nextPath: string): Promise<ConfluenceAttachment[]> {
    return fetchAllPaginated(
      `${this.config.baseUrl}${nextPath}`,
      this.config.baseUrl,
      (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
      confluenceAttachmentSchema,
    );
  }
}
