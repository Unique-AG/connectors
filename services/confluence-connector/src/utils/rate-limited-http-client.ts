import type { Readable } from 'node:stream';
import { Logger } from '@nestjs/common';
import Bottleneck from 'bottleneck';
import { Agent, type Dispatcher, interceptors, request } from 'undici';
import type { Metrics } from '../metrics';
import { handleErrorStatus } from './http-util';

const API_PATH_START = /\/(rest\/api|api\/v2)\//;

/**
 * Extracts a short, normalized endpoint from a full Confluence URL.
 * Keeps only the path starting from `/rest/api/` or `/api/v2/`, strips query params,
 * and replaces numeric/UUID segments with `{id}`.
 * With this we try to reduce entropy for metrics
 *
 * `/ex/confluence/{uuid}/wiki/rest/api/content/12345` → `/rest/api/content/{id}`
 * `/rest/api/content/search?cql=...` → `/rest/api/content/search`
 */
function normalizeEndpoint(url: string): string {
  try {
    const path = new URL(url).pathname;
    const match = API_PATH_START.exec(path);
    if (!match) {
      return path;
    }
    const apiPath = path.slice(match.index);
    return apiPath.replaceAll(/\/[0-9a-f-]{8,}/gi, '/{id}').replaceAll(/\/(att)?\d{2,}/g, '/{id}');
  } catch {
    return 'unknown';
  }
}

// TODO: extract to shared utils package (bottleneck as optional peer dep)
export class RateLimitedHttpClient {
  private readonly logger = new Logger(RateLimitedHttpClient.name);
  private readonly limiter: Bottleneck;
  private readonly dispatcher: Dispatcher;

  public constructor(
    ratePerMinute: number,
    private readonly metrics: Metrics,
  ) {
    this.dispatcher = new Agent().compose([
      interceptors.redirect({ maxRedirections: 10 }),
      interceptors.retry(),
    ]);

    this.limiter = new Bottleneck({
      reservoir: ratePerMinute,
      reservoirRefreshAmount: ratePerMinute,
      reservoirRefreshInterval: 60_000,
    });

    this.setupThrottlingMonitoring();
  }

  public async rateLimitedRequest(url: string, headers: Record<string, string>): Promise<unknown> {
    const body = await this.executeRequest(url, headers);
    return body.json();
  }

  public async rateLimitedStreamRequest(
    url: string,
    headers: Record<string, string>,
  ): Promise<Readable> {
    return this.executeRequest(url, headers);
  }

  private async executeRequest(
    url: string,
    headers: Record<string, string>,
  ): Promise<Dispatcher.ResponseData['body']> {
    return this.limiter.schedule(async () => {
      const startTime = performance.now();
      const endpoint = normalizeEndpoint(url);
      let statusCode: number | undefined;

      try {
        const response = await request(url, {
          method: 'GET',
          headers,
          dispatcher: this.dispatcher,
        });

        statusCode = response.statusCode;
        await handleErrorStatus(response.statusCode, response.body, url);

        this.recordRequestDuration(startTime, endpoint, 'success');
        return response.body;
      } catch (error) {
        this.recordRequestDuration(startTime, endpoint, 'error');
        this.metrics.recordApiError(statusCode);
        throw error;
      }
    });
  }

  private recordRequestDuration(
    startTime: number,
    endpoint: string,
    result: 'success' | 'error',
  ): void {
    const durationSeconds = (performance.now() - startTime) / 1000;
    this.metrics.recordApiRequestDuration(durationSeconds, endpoint, result);
  }

  private setupThrottlingMonitoring(): void {
    this.limiter.on('depleted', () => {
      this.logger.log({ msg: 'Rate limit reservoir depleted - queuing requests' });
      this.metrics.recordApiThrottleEvent();
    });

    this.limiter.on('dropped', () => {
      this.logger.error({ msg: 'Request dropped due to rate limiter queue overflow' });
    });

    this.limiter.on('error', (error) => {
      this.logger.error({ err: error, msg: 'Bottleneck error' });
    });
  }
}
