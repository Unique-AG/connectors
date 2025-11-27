import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { Config } from '../config';

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
  private readonly isDebugEnabled: boolean;

  public constructor(private readonly configService: ConfigService<Config, true>) {
    this.isDebugEnabled = this.configService.get('app.logLevel', { infer: true }) === 'debug';
  }

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

    // Log queue size when requests are queued (only when log level is debug)
    if (this.isDebugEnabled) {
      limiter.on('queued', () => {
        const queueCount = limiter.counts().QUEUED;
        if (queueCount > 1) {
          this.logger.debug(`${contextName}: Rate Limit Queue size reached ${queueCount} requests`);
        }
      });
    }

    // Log dropped requests (queue overflow)
    limiter.on('dropped', () => {
      this.logger.error(
        `${contextName}: Rate limit request dropped due to rate limiter queue overflow`,
      );
    });

    // Log errors
    limiter.on('error', (error) => {
      this.logger.error(`${contextName}: Rate limit bottleneck error: ${error.message}`, error);
    });
  }
}
