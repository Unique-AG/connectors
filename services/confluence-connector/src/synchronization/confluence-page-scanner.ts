import type pino from 'pino';
import type { ConfluenceConfig, ProcessingConfig } from '../config';
import type { ConfluencePage } from '../confluence-api';
import { ConfluenceApiClient, ContentType } from '../confluence-api';
import type { ServiceRegistry } from '../tenant';
import type { DiscoveredPage } from './sync.types';

const SKIPPED_CONTENT_TYPES = [ContentType.DATABASE, ContentType.BLOGPOST, ContentType.WHITEBOARD, ContentType.EMBED];

export class ConfluencePageScanner {
  private readonly apiClient: ConfluenceApiClient;
  private readonly logger: pino.Logger;

  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly processingConfig: ProcessingConfig,
    serviceRegistry: ServiceRegistry,
  ) {
    this.apiClient = serviceRegistry.getService(ConfluenceApiClient);
    this.logger = serviceRegistry.getServiceLogger(ConfluencePageScanner);
  }

  public async discoverPages(): Promise<DiscoveredPage[]> {
    const labeledPages = await this.apiClient.searchPagesByLabel();
    const discovered: DiscoveredPage[] = [];
    const discoveredIds = new Set<string>();

    for (const page of labeledPages) {
      await this.processPage(page, discovered, discoveredIds, false);
    }

    this.logger.info({ count: discovered.length }, 'Page discovery completed');
    return discovered;
  }

  private async expandChildren(
    parent: ConfluencePage,
    discovered: DiscoveredPage[],
    discoveredIds: Set<string>,
  ): Promise<void> {
    let children: ConfluencePage[];
    try {
      children = await this.apiClient.getChildPages(parent.id, parent.type);
    } catch (error) {
      this.logger.warn(
        { parentId: parent.id, title: parent.title, error },
        'Failed to fetch child pages, skipping children',
      );
      return;
    }

    for (const child of children) {
      await this.processPage(child, discovered, discoveredIds, true);
    }
  }

  private async processPage(
    page: ConfluencePage,
    discovered: DiscoveredPage[],
    discoveredIds: Set<string>,
    expandAll: boolean,
  ): Promise<void> {
    if (this.isLimitReached(discovered.length)) {
      return;
    }

    if (SKIPPED_CONTENT_TYPES.includes(page.type)) {
      this.logger.info({ pageId: page.id, title: page.title, type: page.type }, 'Skipping non-page content type');
      return;
    }

    if (discoveredIds.has(page.id)) {
      return;
    }

    discoveredIds.add(page.id);
    discovered.push(this.toDiscoveredPage(page));

    if (expandAll || this.hasIngestAllLabel(page)) {
      await this.expandChildren(page, discovered, discoveredIds);
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
