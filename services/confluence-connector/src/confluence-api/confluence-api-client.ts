import Bottleneck from 'bottleneck';
import type pino from 'pino';
import { Agent, type Dispatcher, interceptors, request } from 'undici';
import type { IncomingHttpHeaders } from 'undici/types/header';
import type { ConfluenceAuth } from '../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../config';
import { handleErrorStatus } from '../utils/http-util';
import type { ConfluencePage, ContentType } from './types/confluence-api.types';


export abstract class ConfluenceApiClient {
  private readonly confluenceAuth: ConfluenceAuth;
  protected readonly logger: pino.Logger;
  private readonly limiter: Bottleneck;
  private readonly dispatcher: Dispatcher;
  protected readonly baseUrl: string;

  public constructor(
    protected readonly config: ConfluenceConfig,
    confluenceAuth: ConfluenceAuth,
    logger: pino.Logger,
  ) {
    this.confluenceAuth = confluenceAuth;
    this.logger = logger;
    this.baseUrl = config.baseUrl;

    this.dispatcher = new Agent().compose([interceptors.redirect(), interceptors.retry()]);

    this.limiter = new Bottleneck({
      reservoir: config.apiRateLimitPerMinute,
      reservoirRefreshAmount: config.apiRateLimitPerMinute,
      reservoirRefreshInterval: 60_000,
    });

    this.setupThrottlingMonitoring();
  }

  public abstract searchPagesByLabel(): Promise<ConfluencePage[]>;

  public abstract getPageById(pageId: string): Promise<ConfluencePage | null>;

  public abstract getChildPages(
    parentId: string,
    contentType: ContentType,
  ): Promise<ConfluencePage[]>;

  public abstract buildPageWebUrl(page: ConfluencePage): string;

  protected async makeRateLimitedRequest(url: string): Promise<unknown> {
    return await this.limiter.schedule(async () => {
      const token = await this.confluenceAuth.acquireToken();
      const response = await request(url, {
        method: 'GET',
        headers: { Authorization: `Bearer ${token}` },
        dispatcher: this.dispatcher,
      });

      this.logRateLimitHeaders(response.headers);
      await handleErrorStatus(response.statusCode, response.body, url);
      return response.body.json();
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

  // TODO: extract BottleneckFactory to shared utils (bottleneck as optional peer dep, separate file like zod helpers)
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
        error,
      });
    });
  }
}
