import Bottleneck from 'bottleneck';
import type pino from 'pino';
import { Agent, type Dispatcher, interceptors, request } from 'undici';
import type { IncomingHttpHeaders } from 'undici/types/header';
import { handleErrorStatus } from './http-util';

// TODO: extract to shared utils package (bottleneck as optional peer dep)
export class RateLimitedHttpClient {
  private readonly limiter: Bottleneck;
  private readonly dispatcher: Dispatcher;

  public constructor(
    private readonly logger: pino.Logger,
    ratePerMinute: number,
  ) {
    this.dispatcher = new Agent().compose([interceptors.redirect(), interceptors.retry()]);

    this.limiter = new Bottleneck({
      reservoir: ratePerMinute,
      reservoirRefreshAmount: ratePerMinute,
      reservoirRefreshInterval: 60_000,
    });

    this.setupThrottlingMonitoring();
  }

  public async rateLimitedRequest(url: string, headers: Record<string, string>): Promise<unknown> {
    return await this.limiter.schedule(async () => {
      const response = await request(url, {
        method: 'GET',
        headers,
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
        msg: 'Rate limit headers',
        'x-ratelimit-remaining': remaining,
        'x-ratelimit-limit': limit,
      });
    }
  }

  private setupThrottlingMonitoring(): void {
    this.limiter.on('depleted', (empty) => {
      if (empty) {
        this.logger.info('Rate limit reservoir depleted - queuing requests');
      }
    });

    this.limiter.on('dropped', () => {
      this.logger.error('Request dropped due to rate limiter queue overflow');
    });

    this.limiter.on('error', (error) => {
      this.logger.error(error, 'Bottleneck error');
    });
  }
}
