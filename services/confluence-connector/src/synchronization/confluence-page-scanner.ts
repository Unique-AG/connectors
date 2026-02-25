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
    const discoveredIds = new Set<string>();
    const labeledPages = await this.apiClient.searchPagesByLabel();

    const filteredPages = this.mapToDiscoveredPages(labeledPages, discoveredIds);

    const ingestAllRootPageIds = labeledPages
      .filter((page) => this.hasIngestAllLabel(page))
      .map((page) => page.id);

    let filteredDescendantPages: DiscoveredPage[] = [];
    if (ingestAllRootPageIds.length > 0) {
      // we are fetching descendants on content marked with ai-ingest-all label regardless of the content type
      const descendants = await this.fetchAllDescendants(ingestAllRootPageIds);
      filteredDescendantPages = this.mapToDiscoveredPages(descendants, discoveredIds);
    }

    const discovered = [...filteredPages, ...filteredDescendantPages];
    this.logger.info({ count: discovered.length }, 'Page discovery completed');
    return discovered;
  }

  private mapToDiscoveredPages(
    pages: ConfluencePage[],
    discoveredIds: Set<string>,
  ): DiscoveredPage[] {
    const discoveredPages: DiscoveredPage[] = [];
    for (const page of pages) {
      if (this.isLimitReached(discoveredIds.size)) {
        break;
      }

      if (SKIPPED_CONTENT_TYPES.includes(page.type)) {
        this.logger.debug(
          { pageId: page.id, title: page.title, type: page.type },
          'Skipping non-page content type',
        );
        continue;
      }

      if (discoveredIds.has(page.id)) {
        continue;
      }

      discoveredIds.add(page.id);

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

  private async fetchAllDescendants(rootIds: string[]): Promise<ConfluencePage[]> {
    try {
      return await this.apiClient.getDescendantPages(rootIds);
    } catch (error) {
      this.logger.error(
        { rootIds, error },
        'Failed to fetch descendant pages, skipping descendants',
      );
      // continue
      return [];
    }
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
