import { Context, Middleware } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import type { Counter, Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';

export class MetricsMiddleware implements Middleware {
  private readonly logger = new Logger(this.constructor.name);
  private nextMiddleware: Middleware | undefined;

  private readonly msgraphRequestCounter: Counter;
  private readonly msgraphRequestDuration: Histogram;
  private readonly msgraphThrottleCounter: Counter;

  public constructor(metricService: MetricService) {
    this.msgraphRequestCounter = metricService.getCounter('msgraph_requests_total', {
      description: 'Total number of Microsoft Graph requests',
    });
    this.msgraphRequestDuration = metricService.getHistogram('msgraph_request_duration_seconds', {
      description: 'Microsoft Graph request duration in seconds',
    });
    this.msgraphThrottleCounter = metricService.getCounter('msgraph_throttle_events_total', {
      description: 'Total number of Microsoft Graph throttling events',
    });
  }

  private extractEndpoint(request: RequestInfo): string {
    try {
      const url = typeof request === 'string' ? request : request.url;
      const urlObj = new URL(url);
      // Remove the base URL and version, keep just the endpoint path
      const endpoint = urlObj.pathname.replace(/^\/v\d+(\.\d+)?/, '');
      return endpoint || '/';
    } catch {
      return 'unknown';
    }
  }

  private extractMethod(options: RequestInit | undefined): string {
    return options?.method?.toUpperCase() || 'GET';
  }

  private getStatusClass(statusCode: number): string {
    if (statusCode >= 200 && statusCode < 300) return '2xx';
    if (statusCode >= 300 && statusCode < 400) return '3xx';
    if (statusCode >= 400 && statusCode < 500) return '4xx';
    if (statusCode >= 500) return '5xx';
    return 'unknown';
  }

  private isThrottled(response: Response | undefined): boolean {
    if (!response) return false;

    // Check for 429 (Too Many Requests) status
    if (response.status === 429) return true;

    // Check for 503 (Service Unavailable) with Retry-After header
    if (response.status === 503 && response.headers.get('Retry-After')) return true;

    return false;
  }

  private getThrottlePolicy(response: Response | undefined): string {
    if (!response) return 'unknown';

    // Check for standard Retry-After header
    const retryAfter = response.headers.get('Retry-After');
    if (retryAfter) {
      return 'retry-after';
    }

    // Check for Rate-Limit headers
    const rateLimit = response.headers.get('RateLimit-Limit');
    if (rateLimit) {
      return 'rate-limit';
    }

    return 'unknown';
  }

  public async execute(context: Context): Promise<void> {
    if (!this.nextMiddleware) throw new Error('Next middleware not set');

    const endpoint = this.extractEndpoint(context.request);
    const method = this.extractMethod(context.options);
    const startTime = Date.now();

    try {
      await this.nextMiddleware.execute(context);

      const duration = Date.now() - startTime;
      const statusCode = context.response?.status || 0;
      const statusClass = this.getStatusClass(statusCode);

      this.msgraphRequestCounter.add(1, {
        endpoint,
        method,
        status_class: statusClass,
      });

      this.msgraphRequestDuration.record(duration / 1000, {
        endpoint,
        method,
      });

      if (this.isThrottled(context.response)) {
        const policy = this.getThrottlePolicy(context.response);
        this.msgraphThrottleCounter.add(1, { policy });

        this.logger.warn(
          {
            method,
            endpoint,
            statusCode,
            throttlePolicy: policy,
            duration: duration,
            rateLimited: true,
          },
          'Microsoft Graph API request was rate-limited and throttled',
        );
      }

      if (duration > 5000) {
        this.logger.warn(
          {
            method,
            endpoint,
            duration,
            thresholdMs: 5000,
            performanceIssue: true,
          },
          'Microsoft Graph API request exceeded performance threshold and is considered slow',
        );
      }
    } catch (error) {
      const duration = Date.now() - startTime;

      this.msgraphRequestCounter.add(1, {
        endpoint,
        method,
        status_class: '5xx',
      });

      this.msgraphRequestDuration.record(duration / 1000, {
        endpoint,
        method,
      });

      this.logger.error(
        'Microsoft Graph API request failed with an error',
        {
          method,
          endpoint,
          duration,
          requestFailed: true,
        },
        error,
      );

      throw error;
    }
  }

  public setNext(next: Middleware): void {
    this.nextMiddleware = next;
  }
}
