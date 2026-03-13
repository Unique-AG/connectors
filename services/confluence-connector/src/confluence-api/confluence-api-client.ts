import type { Readable } from 'node:stream';
import { isNullish } from 'remeda';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import {
  type ConfluenceAttachment,
  type ConfluencePage,
  confluenceAttachmentSchema,
} from './types/confluence-api.types';

export interface ApiClientOptions {
  attachmentsEnabled: boolean;
}

export abstract class ConfluenceApiClient {
  protected abstract readonly paginationBaseUrl: string;

  public abstract searchPagesByLabel(): Promise<ConfluencePage[]>;

  public abstract getPageById(pageId: string): Promise<ConfluencePage | null>;

  public abstract getDescendantPages(rootIds: string[]): Promise<ConfluencePage[]>;

  public abstract buildPageWebUrl(page: ConfluencePage): string;

  public abstract getAttachmentDownloadStream(
    attachmentId: string,
    pageId: string,
    downloadPath: string,
  ): Promise<Readable>;

  protected abstract makeAuthenticatedRequest(url: string): Promise<unknown>;

  protected async fetchAttachments(pages: ConfluencePage[]): Promise<void> {
    for (const page of pages) {
      const attachment = page.children?.attachment;
      if (!attachment) {
        continue;
      }

      const { size, limit, _links } = attachment;
      if (isNullish(size) || isNullish(limit) || size < limit || !_links?.next) {
        continue;
      }

      const remaining = await this.fetchPaginatedAttachments(_links.next);
      attachment.results.push(...remaining);
    }
  }

  private async fetchPaginatedAttachments(nextPath: string): Promise<ConfluenceAttachment[]> {
    return fetchAllPaginated(
      `${this.paginationBaseUrl}${nextPath}`,
      this.paginationBaseUrl,
      (requestUrl) => this.makeAuthenticatedRequest(requestUrl),
      confluenceAttachmentSchema,
    );
  }
}
