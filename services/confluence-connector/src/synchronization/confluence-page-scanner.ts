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

    const filteredPageIds = this.filterIngestablePages(labeledPages, discoveredIds);

    const ingestAllRootIds = labeledPages
      .filter((page) => this.hasIngestAllLabel(page))
      .map((page) => page.id);

    let filteredDescendantPageIds: DiscoveredPage[] = [];
    if (ingestAllRootIds.length > 0) {
      // we are fetching descendants on content marked with ai-ingest-all label regardless of the content type
      const descendants = await this.fetchAllDescendants(ingestAllRootIds);
      filteredDescendantPageIds = this.filterIngestablePages(descendants, discoveredIds);
    }

    const discovered = [...filteredPageIds, ...filteredDescendantPageIds];
    this.logger.info({ count: discovered.length }, 'Page discovery completed');
    return discovered;
  }

  private filterIngestablePages(
    pages: ConfluencePage[],
    discoveredIds: Set<string>,
  ): DiscoveredPage[] {
    const result: DiscoveredPage[] = [];
    for (const page of pages) {
      if (this.isLimitReached(discoveredIds.size)) {
        break;
      }

      if (SKIPPED_CONTENT_TYPES.includes(page.type)) {
        this.logger.info(
          { pageId: page.id, title: page.title, type: page.type },
          'Skipping non-page content type',
        );
        continue;
      }

      // as discoveredIds is a set this is redundant check but is kept for explicitness
      if (discoveredIds.has(page.id)) {
        continue;
      }

      discoveredIds.add(page.id);
      result.push(this.toDiscoveredPage(page));
    }
    return result;
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

  private toDiscoveredPage(page: ConfluencePage): DiscoveredPage {
    return {
      id: page.id,
      title: page.title,
      type: page.type,
      spaceId: page.space.id,
      spaceKey: page.space.key,
      spaceName: page.space.name,
      versionTimestamp: page.version.when,
      webUrl: this.apiClient.buildPageWebUrl(page),
      labels: page.metadata.labels.results.map((label) => label.name),
    };
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
