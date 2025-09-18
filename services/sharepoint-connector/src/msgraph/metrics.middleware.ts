import { Context, Middleware } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';

/**
 * Metrics middleware for Microsoft Graph requests
 */
export class MetricsMiddleware implements Middleware {
  private readonly logger = new Logger(this.constructor.name);
  private nextMiddleware: Middleware | undefined;

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

      this.logger.debug({
        msg: 'SharePoint Graph API request completed',
        endpoint,
        method,
        statusCode,
        statusClass,
        duration,
      });

      if (this.isThrottled(context.response)) {
        const policy = this.getThrottlePolicy(context.response);

        this.logger.warn({
          msg: 'SharePoint Graph API request throttled',
          endpoint,
          method,
          statusCode,
          policy,
          duration,
        });
      }

      if (duration > 5000) {
        this.logger.warn({
          msg: 'Slow SharePoint Graph API request detected',
          endpoint,
          method,
          duration,
          statusCode,
        });
      }
    } catch (error) {
      const duration = Date.now() - startTime;

      this.logger.error({
        msg: 'SharePoint Graph API request failed',
        endpoint,
        method,
        duration,
        error: error instanceof Error ? error.message : String(error),
      });

      throw error;
    }
  }

  public setNext(next: Middleware): void {
    this.nextMiddleware = next;
  }
}
