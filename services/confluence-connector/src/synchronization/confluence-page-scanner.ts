import type pino from 'pino';
import type { ConfluenceConfig, ProcessingConfig } from '../config';
import type { ConfluencePage } from '../confluence-api';
import { type ConfluenceApiClient, ContentType } from '../confluence-api';
import type { DiscoveredPage } from './sync.types';

const SKIPPED_CONTENT_TYPES = [ContentType.DATABASE, ContentType.BLOGPOST, ContentType.WHITEBOARD, ContentType.EMBED];

export class ConfluencePageScanner {
  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly processingConfig: ProcessingConfig,
    private readonly apiClient: ConfluenceApiClient,
    private readonly logger: pino.Logger,
  ) {}

  public async discoverPages(): Promise<DiscoveredPage[]> {
    const labeledPages = await this.apiClient.searchPagesByLabel();
    const discovered: DiscoveredPage[] = [];
    const discoveredIds = new Set<string>();
    const ingestAllRootIds: string[] = [];

    for (const page of labeledPages) {
      if (this.isLimitReached(discovered.length)) break;

      if (SKIPPED_CONTENT_TYPES.includes(page.type)) {
        this.logger.info({ pageId: page.id, title: page.title, type: page.type }, 'Skipping non-page content type');
        continue;
      }

      if (discoveredIds.has(page.id)) continue;

      discoveredIds.add(page.id);
      discovered.push(this.toDiscoveredPage(page));

      if (this.hasIngestAllLabel(page)) {
        ingestAllRootIds.push(page.id);
      }
    }

    if (ingestAllRootIds.length > 0) {
      await this.expandDescendants(ingestAllRootIds, discovered, discoveredIds);
    }

    this.logger.info({ count: discovered.length }, 'Page discovery completed');
    return discovered;
  }

  private async expandDescendants(
    rootIds: string[],
    discovered: DiscoveredPage[],
    discoveredIds: Set<string>,
  ): Promise<void> {
    let descendants: ConfluencePage[];
    try {
      descendants = await this.apiClient.getDescendantPages(rootIds);
    } catch (error) {
      this.logger.warn(
        { rootIds, error },
        'Failed to fetch descendant pages, skipping descendants',
      );
      return;
    }

    for (const page of descendants) {
      if (this.isLimitReached(discovered.length)) {
        break;
      }

      if (SKIPPED_CONTENT_TYPES.includes(page.type)) {
        this.logger.debug({ pageId: page.id, title: page.title, type: page.type }, 'Skipping non-page content type');
        continue;
      }

      if (discoveredIds.has(page.id)) {
        continue;
      }

      discoveredIds.add(page.id);
      discovered.push(this.toDiscoveredPage(page));
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
