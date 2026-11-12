import { Logger } from '@nestjs/common';
import { ZodError } from 'zod';
import type { ConfluenceConfig } from '../config';
import type { ConfluenceApiClient, ConfluencePage } from '../confluence-api';
import { HttpStatusError } from '../utils/http-util';
import type { DiscoveredPage, FetchedPage } from './sync.types';

export class ConfluenceContentFetcher {
  private readonly logger = new Logger(ConfluenceContentFetcher.name);

  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly apiClient: ConfluenceApiClient,
  ) {}

  public async fetchPageContent(page: DiscoveredPage): Promise<FetchedPage | null> {
    const fullPage = await this.fetchFullPage(page);

    if (!fullPage) {
      this.logger.warn({
        pageId: page.id,
        title: page.title,
        msg: 'Page not found, possibly deleted',
      });
      return null;
    }

    const body = fullPage.body?.storage?.value || '';
    if (!body) {
      this.logger.debug({
        pageId: page.id,
        title: page.title,
        msg: 'Page has no body, skipping',
      });
      return null;
    }

    const confluenceLabels = this.extractLabels(fullPage.metadata.labels.results);
    const metadata = confluenceLabels.length > 0 ? { confluenceLabels } : undefined;

    this.logger.debug({
      pageId: page.id,
      title: page.title,
      msg: 'Page content fetched',
    });

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

  private async fetchFullPage(page: DiscoveredPage): Promise<ConfluencePage | null> {
    try {
      return await this.apiClient.getPageById(page.id);
    } catch (err) {
      this.logger.error({
        pageId: page.id,
        title: page.title,
        ...describeFetchError(err),
        msg: 'Failed to fetch page',
      });
      throw err;
    }
  }

  private extractLabels(labels: Array<{ name: string }>): string[] {
    const ingestLabels = [
      this.confluenceConfig.ingestSingleLabel,
      this.confluenceConfig.ingestAllLabel,
    ];

    // Sorted alphabetically required for deterministic label ordering in downstream consumers
    return labels
      .map((label) => label.name)
      .filter((name) => !ingestLabels.includes(name))
      .sort();
  }
}

// Error messages can carry Confluence response bodies, so only their shape is logged.
function describeFetchError(err: unknown): Record<string, unknown> {
  if (err instanceof HttpStatusError) {
    return { errorName: err.name, statusCode: err.statusCode };
  }
  if (err instanceof ZodError) {
    return {
      errorName: err.name,
      issues: err.issues.map(({ code, path }) => ({ code, path: path.map(String).join('.') })),
    };
  }
  return { errorName: err instanceof Error ? err.name : typeof err };
}
