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

  public abstract getAttachmentDownloadStream(downloadPath: string): Promise<Readable>;
}
