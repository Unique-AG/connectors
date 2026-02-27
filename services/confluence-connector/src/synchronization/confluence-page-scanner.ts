import type pino from 'pino';
import type { ConfluenceConfig, ProcessingConfig } from '../config';
import type { ConfluencePage } from '../confluence-api';
import { type ConfluenceApiClient, ContentType } from '../confluence-api';
import type { DiscoveredPage } from './sync.types';

const SKIPPED_CONTENT_TYPES = [
  ContentType.DATABASE,
  ContentType.BLOGPOST,
  ContentType.WHITEBOARD,
  ContentType.EMBED,
];

export class ConfluencePageScanner {
  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly processingConfig: ProcessingConfig,
    private readonly apiClient: ConfluenceApiClient,
    private readonly logger: pino.Logger,
  ) {}

  public async discoverPages(): Promise<DiscoveredPage[]> {
    const seenPageIds = new Set<string>();
    const labeledPages = await this.apiClient.searchPagesByLabel();
    const discoveredPages = this.mapToDiscoveredPages(labeledPages, seenPageIds);

    const ingestAllRootPageIds = labeledPages
      .filter((page) => this.hasIngestAllLabel(page))
      .map((page) => page.id);

    if (ingestAllRootPageIds.length > 0) {
      // we are fetching descendants on content marked with ai-ingest-all label regardless of the content type
      const descendants = await this.apiClient.getDescendantPages(ingestAllRootPageIds);
      const mappedDescendantPages = this.mapToDiscoveredPages(descendants, seenPageIds);
      discoveredPages.push(...mappedDescendantPages);
    }

    this.logger.info({ count: discoveredPages.length }, 'Page discovery completed');
    return discoveredPages;
  }

  private mapToDiscoveredPages(
    pages: ConfluencePage[],
    seenPageIds: Set<string>,
  ): DiscoveredPage[] {
    const discoveredPages: DiscoveredPage[] = [];
    for (const page of pages) {
      if (this.isLimitReached(seenPageIds.size)) {
        break;
      }

      if (SKIPPED_CONTENT_TYPES.includes(page.type)) {
        this.logger.debug(
          { pageId: page.id, title: page.title, type: page.type },
          'Skipping non-page content type',
        );
        continue;
      }

      if (seenPageIds.has(page.id)) {
        continue;
      }

      seenPageIds.add(page.id);

      discoveredPages.push({
        id: page.id,
        title: page.title,
        type: page.type,
        spaceId: page.space.id,
        spaceKey: page.space.key,
        spaceName: page.space.name,
        versionTimestamp: page.version.when,
        webUrl: this.apiClient.buildPageWebUrl(page),
        labels: page.metadata.labels.results.map((label) => label.name),
      });
    }

    return discoveredPages;
  }

  private hasIngestAllLabel(page: ConfluencePage): boolean {
    return page.metadata.labels.results.some(
      (label) => label.name === this.confluenceConfig.ingestAllLabel,
    );
  }

  private isLimitReached(currentCount: number): boolean {
    const limit = this.processingConfig.maxPagesToScan;
    if (limit === undefined) {
      return false;
    }
    if (currentCount >= limit) {
      this.logger.info({ limit }, 'maxPagesToScan limit reached');
      return true;
    }
    return false;
  }
}
