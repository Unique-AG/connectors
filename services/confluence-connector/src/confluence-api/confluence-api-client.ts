import type { Readable } from 'node:stream';
import type { ConfluencePage } from './types/confluence-api.types';

export interface ApiClientOptions {
  attachmentsEnabled: boolean;
}

export abstract class ConfluenceApiClient {
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

  /**
   * The initial search request returns up to 25 attachments per page via the
   * `expand=children.attachment` parameter. When a page has more than 25,
   * this method fetches the remaining attachments.
   */
  protected abstract fetchMoreAttachments(pages: ConfluencePage[]): Promise<void>;
}
