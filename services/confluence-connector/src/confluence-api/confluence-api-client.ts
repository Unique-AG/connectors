import Bottleneck from 'bottleneck';
import type pino from 'pino';
import { Agent, type Dispatcher, interceptors, request } from 'undici';
import type { IncomingHttpHeaders } from 'undici/types/header';
import { ConfluenceAuth } from '../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../config';
import type { ServiceRegistry } from '../tenant/service-registry';
import { handleErrorStatus } from '../utils/http-util';
import { sanitizeError } from '../utils/normalize-error';
import type { ConfluenceApiAdapter } from './confluence-api-adapter';
import { fetchAllPaginated } from './confluence-fetch-paginated';
import type { ConfluencePage, ContentType } from './types/confluence-api.types';

const SEARCH_PAGE_SIZE = 25;

export class ConfluenceApiClient {
  private readonly confluenceAuth: ConfluenceAuth;
  private readonly logger: pino.Logger;
  private readonly limiter: Bottleneck;
  private readonly dispatcher: Dispatcher;

  public constructor(
    private readonly adapter: ConfluenceApiAdapter,
    private readonly config: ConfluenceConfig,
    serviceRegistry: ServiceRegistry,
  ) {
    this.confluenceAuth = serviceRegistry.getService(ConfluenceAuth);
    this.logger = serviceRegistry.getServiceLogger(ConfluenceApiClient);

    this.dispatcher = new Agent().compose([interceptors.redirect(), interceptors.retry()]);

    this.limiter = new Bottleneck({
      reservoir: config.apiRateLimitPerMinute,
      reservoirRefreshAmount: config.apiRateLimitPerMinute,
      reservoirRefreshInterval: 60_000,
    });

    this.setupThrottlingMonitoring();
  }

  public async searchPagesByLabel(): Promise<ConfluencePage[]> {
    const spaceTypeFilter =
      this.config.instanceType === 'cloud'
        ? '(space.type=global OR space.type=collaboration)'
        : 'space.type=global';
    const cql = `((label="${this.config.ingestSingleLabel}") OR (label="${this.config.ingestAllLabel}")) AND ${spaceTypeFilter} AND type != attachment`;

    const initialUrl = this.adapter.buildSearchUrl(cql, SEARCH_PAGE_SIZE, 0);
    return fetchAllPaginated<ConfluencePage>(initialUrl, this.config.baseUrl, (url) =>
      this.makeRateLimitedRequest(url),
    );
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const url = this.adapter.buildGetPageUrl(pageId);
    const body = await this.makeRateLimitedRequest<unknown>(url);
    return this.adapter.parseSinglePageResponse(body);
  }

  public async getChildPages(
    parentId: string,
    contentType: ContentType,
  ): Promise<ConfluencePage[]> {
    return this.adapter.fetchChildPages(parentId, contentType, (url) =>
      this.makeRateLimitedRequest(url),
    );
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return this.adapter.buildPageWebUrl(page);
  }

  private async makeRateLimitedRequest<T>(url: string): Promise<T> {
    return await this.limiter.schedule(async () => {
      const token = await this.confluenceAuth.acquireToken();
      const response = await request(url, {
        method: 'GET',
        headers: { Authorization: `Bearer ${token}` },
        dispatcher: this.dispatcher,
      });

      this.logRateLimitHeaders(response.headers);
      await handleErrorStatus(response.statusCode, response.body, url);
      return (await response.body.json()) as T;
    });
  }

  private logRateLimitHeaders(headers: IncomingHttpHeaders): void {
    const remaining = headers['x-ratelimit-remaining'];
    const limit = headers['x-ratelimit-limit'];
    if (remaining !== undefined || limit !== undefined) {
      this.logger.info({
        msg: 'Confluence rate limit headers',
        'x-ratelimit-remaining': remaining,
        'x-ratelimit-limit': limit,
      });
    }
  }

  private setupThrottlingMonitoring(): void {
    this.limiter.on('depleted', (empty) => {
      if (empty) {
        this.logger.info('Confluence API: Rate limit reservoir depleted - queuing requests');
      }
    });

    this.limiter.on('dropped', () => {
      this.logger.error('Confluence API: Request dropped due to rate limiter queue overflow');
    });

    this.limiter.on('error', (error) => {
      this.logger.error({
        msg: 'Confluence API: Bottleneck error',
        error: sanitizeError(error),
      });
    });
  }
}
