import { Logger } from '@nestjs/common';
import { createSmeared } from '@unique-ag/utils';
import type { ConfluenceConfig } from '../config';
import type { ConfluenceApiClient, ConfluencePage } from '../confluence-api';
import type { DiscoveredPage, FetchedPage } from './sync.types';

export class ConfluenceContentFetcher {
  private readonly logger = new Logger(ConfluenceContentFetcher.name);

  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly apiClient: ConfluenceApiClient,
  ) {}

  public async fetchPageContent(page: DiscoveredPage): Promise<FetchedPage | null> {
    let fullPage: ConfluencePage | null;
    try {
      fullPage = await this.apiClient.getPageById(page.id);
    } catch (error) {
      this.logger.error({
        pageId: page.id,
        title: createSmeared(page.title),
        err: error,
        msg: 'Failed to fetch page, possibly deleted in the meantime',
      });
      return null;
    }

    if (!fullPage) {
      this.logger.warn({
        pageId: page.id,
        title: createSmeared(page.title),
        msg: 'Page not found, possibly deleted',
      });
      return null;
    }

    const body = fullPage.body?.storage?.value || '';
    if (!body) {
      this.logger.log({ pageId: page.id, title: createSmeared(page.title), msg: 'Page has no body, skipping' });
      return null;
    }

    const confluenceLabels = this.extractLabels(fullPage.metadata.labels.results);
    const metadata = confluenceLabels.length > 0 ? { confluenceLabels } : undefined;

    this.logger.debug({ pageId: page.id, title: createSmeared(page.title), msg: 'Page content fetched' });

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

    return labels.map((label) => label.name).filter((name) => !ingestLabels.includes(name));
  }
}
