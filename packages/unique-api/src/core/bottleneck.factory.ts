import type pino from 'pino';
import Bottleneck from 'bottleneck';

export interface BottleneckConfig {
  reservoir: number;
  reservoirRefreshAmount: number;
  reservoirRefreshInterval: number;
  maxConcurrent?: number;
  minTime?: number;
}

export class BottleneckFactory {
  public constructor(private readonly logger: pino.Logger) {}

  public createLimiter(config: BottleneckConfig, contextName: string): Bottleneck {
    const limiter = new Bottleneck(config);
    this.setupThrottlingMonitoring(limiter, contextName);
    return limiter;
  }

  private setupThrottlingMonitoring(limiter: Bottleneck, contextName: string): void {
    // Log when rate limit reservoir is depleted (rate limit hit)
    limiter.on('depleted', (empty) => {
      if (empty) {
        this.logger.info(`${contextName}: Rate limit reservoir depleted - queuing requests`);
      }
    });

    // Log dropped requests (queue overflow)
    limiter.on('dropped', () => {
      this.logger.error(
        `${contextName}: Rate limit request dropped due to rate limiter queue overflow`,
      );
    });

    // Log errors
    limiter.on('error', (err) => {
      this.logger.error({ err }, `${contextName}: Rate limit bottleneck error`);
    });
  }
}
