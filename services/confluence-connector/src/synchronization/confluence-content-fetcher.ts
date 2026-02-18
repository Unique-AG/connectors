import type pino from 'pino';
import type { ConfluenceConfig } from '../config';
import { ConfluenceApiClient } from '../confluence-api';
import type { ServiceRegistry } from '../tenant';
import { sanitizeError } from '../utils/normalize-error';
import type { DiscoveredPage, FetchedPage } from './sync.types';

export class ConfluenceContentFetcher {
  private readonly apiClient: ConfluenceApiClient;
  private readonly logger: pino.Logger;

  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    serviceRegistry: ServiceRegistry,
  ) {
    this.apiClient = serviceRegistry.getService(ConfluenceApiClient);
    this.logger = serviceRegistry.getServiceLogger(ConfluenceContentFetcher);
  }

  public async fetchPagesContent(pages: DiscoveredPage[]): Promise<FetchedPage[]> {
    const fetched: FetchedPage[] = [];

    for (const page of pages) {
      const result = await this.fetchPage(page);
      if (result) {
        fetched.push(result);
      }
    }

    this.logger.info({ count: fetched.length, total: pages.length }, 'Content fetching completed');
    return fetched;
  }

  private async fetchPage(page: DiscoveredPage): Promise<FetchedPage | null> {
    let fullPage;
    try {
      fullPage = await this.apiClient.getPageById(page.id);
    } catch (error) {
      this.logger.warn(
        { pageId: page.id, title: page.title, error: sanitizeError(error) },
        'Failed to fetch page, possibly deleted in the meantime',
      );
      return null;
    }

    if (!fullPage) {
      this.logger.warn({ pageId: page.id, title: page.title }, 'Page not found, possibly deleted');
      return null;
    }

    const body = fullPage.body?.storage?.value || '';
    if (!body) {
      this.logger.info({ pageId: page.id, title: page.title }, 'Page has no body, skipping');
      return null;
    }

    const confluenceLabels = this.extractLabels(fullPage.metadata.labels.results);
    const metadata = confluenceLabels.length > 0 ? { confluenceLabels } : undefined;

    this.logger.debug({ pageId: page.id, title: page.title }, 'Page content fetched');

    return {
      id: page.id,
      title: page.title,
      body,
      webUrl: page.webUrl,
      spaceId: page.spaceId,
      spaceKey: page.spaceKey,
      spaceName: page.spaceName,
      metadata,
    };
  }

  private extractLabels(labels: Array<{ name: string }>): string[] {
    const ingestLabels = [
      this.confluenceConfig.ingestSingleLabel,
      this.confluenceConfig.ingestAllLabel,
    ];

    return labels
      .map((label) => label.name)
      .filter((name) => !ingestLabels.includes(name));
  }
}
