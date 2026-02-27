import type { ConfluencePage } from './types/confluence-api.types';

export abstract class ConfluenceApiClient {
  public abstract searchPagesByLabel(): Promise<ConfluencePage[]>;

  public abstract getPageById(pageId: string): Promise<ConfluencePage | null>;

  public abstract getDescendantPages(rootIds: string[]): Promise<ConfluencePage[]>;

  public abstract buildPageWebUrl(page: ConfluencePage): string;
}
