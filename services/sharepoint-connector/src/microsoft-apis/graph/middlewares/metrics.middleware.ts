import {
  Context,
  GraphClientError,
  GraphError,
  Middleware,
} from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { GraphApiErrorResponse, isGraphApiError } from '../types/sharepoint.types';

export class MetricsMiddleware implements Middleware {
  private readonly logger = new Logger(this.constructor.name);
  private nextMiddleware: Middleware | undefined;

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
        msg: 'Graph API request completed',
        endpoint,
        method,
        statusCode,
        statusClass,
        duration,
      });

      if (this.isThrottled(context.response)) {
        const policy = this.getThrottlePolicy(context.response);

        this.logger.warn({
          msg: 'Graph API request throttled',
          endpoint,
          method,
          statusCode,
          policy,
          duration,
        });
      }

      if (duration > 5000) {
        this.logger.warn({
          msg: 'Slow Graph API request detected',
          endpoint,
          method,
          duration,
          statusCode,
        });
      }
    } catch (error) {
      const duration = Date.now() - startTime;

      const errorDetails = this.extractGraphErrorDetails(error);

      this.logger.error({
        msg: 'Graph API request failed',
        endpoint,
        method,
        duration,
        error: errorDetails,
      });

      throw error;
    }
  }

  public setNext(next: Middleware): void {
    this.nextMiddleware = next;
  }

  private extractEndpoint(request: RequestInfo): string {
    try {
      const url = typeof request === 'string' ? request : request.url;
      const urlObj = new URL(url);
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

  private extractGraphErrorDetails(error: unknown): Record<string, unknown> {
    const details: Record<string, unknown> = {};

    if (error instanceof Error) {
      details.message = error.message;
      details.name = error.name;
      details.stack = error.stack;
    }

    if (error instanceof GraphError) {
      return {
        ...details,
        statusCode: error.statusCode,
        code: error.code,
        body: error.body,
        requestId: error.requestId,
        date: error.date,
        headers: this.extractHeadersSafely(error.headers),
      };
    }

    if (error instanceof GraphClientError && error.customError) {
      return { ...details, customError: error.customError };
    }

    if (isGraphApiError(error)) {
      const fields: (keyof GraphApiErrorResponse)[] = [
        'statusCode',
        'code',
        'body',
        'requestId',
        'innerError',
      ];

      fields.forEach((field) => {
        if (error[field] !== undefined) {
          details[field] = error[field];
        }
      });

      if (error.response) {
        Object.assign(details, {
          httpStatus: error.response.status,
          headers: this.extractHeadersSafely(error.response.headers),
        });
      }
    }

    return details;
  }

  private extractHeadersSafely(headers: unknown) {
    if (!headers) return undefined;

    if (headers instanceof Headers) {
      return Object.fromEntries(headers.entries());
    }
    return headers;
  }
}
