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

  public abstract buildAttachmentWebUrl(
    pageId: string,
    attachmentId: string,
    attachmentTitle: string,
  ): string;

  public abstract getAttachmentDownloadStream(
    attachmentId: string,
    pageId: string,
    downloadPath: string,
  ): Promise<Readable>;

  protected async fetchMoreAttachments(_pages: ConfluencePage[]): Promise<void> {}
}
