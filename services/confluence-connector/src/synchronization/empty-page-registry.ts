import type { DiscoveredPage } from './sync.types';

/**
 * Remembers the version at which a page had an empty body. An empty page is never stored in
 * Unique, so the file diff reports it as new on every sync. Until the page is edited, which gives
 * it a new version, it can be skipped without fetching it. The record lives in memory, so after a
 * pod start each empty page is fetched once more.
 */
export class EmptyPageRegistry {
  private readonly emptyVersionByPageId = new Map<string, string>();

  public isKnownEmpty(page: DiscoveredPage): boolean {
    return this.emptyVersionByPageId.get(page.id) === page.versionTimestamp;
  }

  public markEmpty(page: DiscoveredPage): void {
    this.emptyVersionByPageId.set(page.id, page.versionTimestamp);
  }

  public forget(pageId: string): void {
    this.emptyVersionByPageId.delete(pageId);
  }

  /** Drops pages that discovery no longer returns, which bounds the record by the discovered pages. */
  public retainOnly(discoveredPages: readonly DiscoveredPage[]): void {
    const discoveredIds = new Set(discoveredPages.map((page) => page.id));
    for (const pageId of this.emptyVersionByPageId.keys()) {
      if (!discoveredIds.has(pageId)) {
        this.emptyVersionByPageId.delete(pageId);
      }
    }
  }
}
