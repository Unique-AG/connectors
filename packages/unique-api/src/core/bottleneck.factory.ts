import { Injectable, Logger } from '@nestjs/common';
import Bottleneck from 'bottleneck';

export interface BottleneckConfig {
  reservoir: number;
  reservoirRefreshAmount: number;
  reservoirRefreshInterval: number;
  maxConcurrent?: number;
  minTime?: number;
}

@Injectable()
export class BottleneckFactory {
  private readonly logger = new Logger(this.constructor.name);

  public constructor() {}

  public createLimiter(config: BottleneckConfig, contextName: string): Bottleneck {
    const limiter = new Bottleneck(config);
    this.setupThrottlingMonitoring(limiter, contextName);
    return limiter;
  }

  private setupThrottlingMonitoring(limiter: Bottleneck, contextName: string): void {
    // Log when rate limit reservoir is depleted (rate limit hit)
    limiter.on('depleted', (empty) => {
      if (empty) {
        this.logger.log(`${contextName}: Rate limit reservoir depleted - queuing requests`);
      }
    });

    // Log dropped requests (queue overflow)
    limiter.on('dropped', () => {
      this.logger.error({
        msg: `${contextName}: Rate limit request dropped due to rate limiter queue overflow`,
      });
    });

    // Log errors
    limiter.on('error', (error) => {
      this.logger.error({ msg: `${contextName}: Rate limit bottleneck error`, error });
    });
  }
}
