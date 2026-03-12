import type { Readable } from 'node:stream';
import { Logger } from '@nestjs/common';
import Bottleneck from 'bottleneck';
import { Agent, type Dispatcher, interceptors, request } from 'undici';
import { handleErrorStatus } from './http-util';

// TODO: extract to shared utils package (bottleneck as optional peer dep)
export class RateLimitedHttpClient {
  private readonly logger = new Logger(RateLimitedHttpClient.name);
  private readonly limiter: Bottleneck;
  private readonly dispatcher: Dispatcher;

  public constructor(ratePerMinute: number) {
    this.dispatcher = new Agent().compose([interceptors.redirect(), interceptors.retry()]);

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
      const response = await request(url, {
        method: 'GET',
        headers,
        dispatcher: this.dispatcher,
      });

      await handleErrorStatus(response.statusCode, response.body, url);
      return response.body;
    });
  }

  private setupThrottlingMonitoring(): void {
    this.limiter.on('depleted', (empty) => {
      if (empty) {
        this.logger.log({ msg: 'Rate limit reservoir depleted - queuing requests' });
      }
    });

    this.limiter.on('dropped', () => {
      this.logger.error({ msg: 'Request dropped due to rate limiter queue overflow' });
    });

    this.limiter.on('error', (error) => {
      this.logger.error({ err: error, msg: 'Bottleneck error' });
    });
  }
}
