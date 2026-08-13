import type { Readable } from 'node:stream';
import { elapsedSeconds } from '@unique-ag/utils';
import { Logger } from '@nestjs/common';
import Bottleneck from 'bottleneck';
import { Agent, type Dispatcher, interceptors, request } from 'undici';
import type { Metrics } from '../metrics';
import { handleErrorStatus } from './http-util';

const API_PATH_START = /\/(rest\/api|api\/v2)\//;
const MAX_REDIRECTS = 10;
const REDIRECT_STATUS_CODES = new Set([301, 302, 303, 307, 308]);

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
    // Safe to replace broadly here — apiPath only contains segments after /rest/api/ or /api/v2/,
    // where numeric segments are content/attachment IDs (typically 5+ digits, sometimes prefixed with "att").
    const apiPath = path.slice(match.index);
    return apiPath.replaceAll(/\/[0-9a-f-]{8,}/gi, '/{id}').replaceAll(/\/(att)?\d{4,}/g, '/{id}');
  } catch {
    return 'unknown';
  }
}

// TODO: extract to shared utils package (bottleneck as optional peer dep)
export class RateLimitedHttpClient {
  private readonly logger = new Logger(RateLimitedHttpClient.name);
  private readonly limiter: Bottleneck;
  private readonly dispatcher: Dispatcher;
  private readonly redirectDispatcher: Dispatcher;

  public constructor(
    ratePerMinute: number,
    private readonly metrics: Metrics,
    dispatcher?: Dispatcher,
  ) {
    const baseDispatcher = dispatcher ?? new Agent();
    this.dispatcher = baseDispatcher.compose([interceptors.retry()]);
    this.redirectDispatcher = baseDispatcher.compose([
      interceptors.redirect({ maxRedirections: MAX_REDIRECTS }),
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
    const body = await this.executeRequest(url, (target) =>
      this.sendFollowingSameOriginRedirects(target, headers),
    );
    return body.json();
  }

  public async rateLimitedStreamRequest(
    url: string,
    headers: Record<string, string>,
  ): Promise<Readable> {
    return this.executeRequest(url, (target) =>
      request(target, { method: 'GET', headers, dispatcher: this.redirectDispatcher }),
    );
  }

  // Undici's redirect interceptor drops the Authorization header whenever a redirect changes origin,
  // which silently downgrades an authenticated API call to an anonymous one instead of failing.
  // Same-origin redirects keep the header and are common on context-path deployments, so we follow
  // those ourselves and surface a cross-origin one as a configuration error.
  private async sendFollowingSameOriginRedirects(
    url: string,
    headers: Record<string, string>,
  ): Promise<Dispatcher.ResponseData> {
    let currentUrl = url;

    for (let redirects = 0; redirects <= MAX_REDIRECTS; redirects++) {
      const response = await request(currentUrl, {
        method: 'GET',
        headers,
        dispatcher: this.dispatcher,
      });

      const { location } = response.headers;
      if (!REDIRECT_STATUS_CODES.has(response.statusCode) || typeof location !== 'string') {
        return response;
      }

      const target = new URL(location, currentUrl);
      if (target.origin !== new URL(currentUrl).origin) {
        await response.body.dump();
        throw new Error(
          `${currentUrl} redirected to a different origin (${target.origin}). Credentials cannot be forwarded across origins, so the request would run unauthenticated. Point the configured baseUrl at ${target.origin} instead.`,
        );
      }

      await response.body.dump();
      currentUrl = target.toString();
    }

    throw new Error(`${url} exceeded ${MAX_REDIRECTS} redirects`);
  }

  private async executeRequest(
    url: string,
    send: (url: string) => Promise<Dispatcher.ResponseData>,
  ): Promise<Dispatcher.ResponseData['body']> {
    return this.limiter.schedule(async () => {
      const startTime = Date.now();
      const endpoint = normalizeEndpoint(url);
      let statusCode: number | undefined;

      try {
        const response = await send(url);

        statusCode = response.statusCode;
        await handleErrorStatus(response.statusCode, response.body, url);

        this.recordRequestDuration(startTime, endpoint, 'success');
        return response.body;
      } catch (err) {
        this.recordRequestDuration(startTime, endpoint, 'error');
        this.metrics.recordApiError(statusCode);
        throw err;
      }
    });
  }

  private recordRequestDuration(
    startTime: number,
    endpoint: string,
    result: 'success' | 'error',
  ): void {
    this.metrics.recordApiRequestDuration(elapsedSeconds(startTime), endpoint, result);
  }

  private setupThrottlingMonitoring(): void {
    this.limiter.on('depleted', () => {
      this.logger.log({ msg: 'Rate limit reservoir depleted - queuing requests' });
      this.metrics.recordApiThrottleEvent();
    });

    this.limiter.on('dropped', () => {
      this.logger.error({ msg: 'Request dropped due to rate limiter queue overflow' });
    });

    this.limiter.on('error', (err) => {
      this.logger.error({ err, msg: 'Bottleneck error' });
    });
  }
}
