import {
  Context,
  GraphClientError,
  GraphError,
  Middleware,
} from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import type { ConfigService } from '@nestjs/config';
import { type Counter, type Histogram } from '@opentelemetry/api';
import type { Config } from '../../../config';
import {
  createApiMethodExtractor,
  getHttpStatusCodeClass,
  getSlowRequestDurationBucket,
} from '../../../metrics';
import {
  redactSiteNameFromPath,
  shouldConcealLogs,
  smearSiteIdFromPath,
} from '../../../utils/logging.util';
import type { Smeared } from '../../../utils/smeared';
import { elapsedMilliseconds, elapsedSeconds } from '../../../utils/timing.util';
import { GraphApiErrorResponse, isGraphApiError } from '../types/sharepoint.types';

export class MetricsMiddleware implements Middleware {
  private readonly logger = new Logger(this.constructor.name);
  private readonly shouldConcealLogs: boolean;
  private nextMiddleware: Middleware | undefined;
  private readonly extractApiMethod: ReturnType<typeof createApiMethodExtractor>;

  private readonly msTenantId: Smeared<string>;

  public constructor(
    private readonly spcGraphApiRequestDurationSeconds: Histogram,
    private readonly spcGraphApiThrottleEventsTotal: Counter,
    private readonly spcGraphApiSlowRequestsTotal: Counter,
    configService: ConfigService<Config, true>,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(configService);
    this.msTenantId = configService.get('sharepoint.tenantId', { infer: true });

    this.extractApiMethod = createApiMethodExtractor([
      'sites',
      'drives',
      'items',
      'children',
      'content',
      'lists',
      'permissions',
      'groups',
      'members',
      'owners',
    ]);
  }

  public async execute(context: Context): Promise<void> {
    if (!this.nextMiddleware) throw new Error('Next middleware not set');

    const loggedEndpoint = this.extractEndpoint(context.request);
    const httpMethod = this.extractMethod(context.options);
    const apiMethod = this.extractApiMethod(loggedEndpoint, httpMethod);

    const startTime = Date.now();

    try {
      await this.nextMiddleware.execute(context);

      const statusClass = getHttpStatusCodeClass(context.response?.status || 0);

      this.spcGraphApiRequestDurationSeconds.record(elapsedSeconds(startTime), {
        ms_tenant_id: this.msTenantId.toString(),
        api_method: apiMethod,
        result: 'success',
        http_status_class: statusClass,
      });

      this.logger.debug({
        msg: 'Graph API request completed',
        endpoint: loggedEndpoint,
        method: httpMethod,
        statusCode: statusClass,
        duration: elapsedMilliseconds(startTime),
      });

      if (this.isThrottled(context.response)) {
        const policy = this.getThrottlePolicy(context.response);

        this.spcGraphApiThrottleEventsTotal.add(1, {
          ms_tenant_id: this.msTenantId.toString(),
          api_method: apiMethod,
          policy,
        });

        this.logger.warn({
          msg: 'Graph API request throttled',
          endpoint: loggedEndpoint,
          method: httpMethod,
          statusCode: statusClass,
          policy,
          duration: elapsedMilliseconds(startTime),
        });
      }

      const duration = elapsedMilliseconds(startTime);
      const slowRequestDurationBucket = getSlowRequestDurationBucket(duration);
      if (slowRequestDurationBucket) {
        this.spcGraphApiSlowRequestsTotal.add(1, {
          ms_tenant_id: this.msTenantId.toString(),
          api_method: apiMethod,
          duration_bucket: slowRequestDurationBucket,
        });

        this.logger.warn({
          msg: 'Slow Graph API request detected',
          endpoint: loggedEndpoint,
          method: httpMethod,
          duration,
          durationBucket: slowRequestDurationBucket,
        });
      }
    } catch (error) {
      const errorDetails = this.extractGraphErrorDetails(error);
      const statusClass = getHttpStatusCodeClass(this.extractStatusCodeFromError(error));
      const duration = elapsedMilliseconds(startTime);

      this.spcGraphApiRequestDurationSeconds.record(elapsedSeconds(startTime), {
        ms_tenant_id: this.msTenantId.toString(),
        api_method: apiMethod,
        result: 'error',
        http_status_class: statusClass,
      });

      const slowRequestDurationBucket = getSlowRequestDurationBucket(duration);
      if (slowRequestDurationBucket) {
        this.spcGraphApiSlowRequestsTotal.add(1, {
          ms_tenant_id: this.msTenantId.toString(),
          api_method: apiMethod,
          duration_bucket: slowRequestDurationBucket,
        });
      }

      this.logger.error({
        msg: 'Graph API request failed',
        endpoint: loggedEndpoint,
        method: httpMethod,
        statusCode: statusClass,
        duration,
        error: errorDetails,
      });

      throw error;
    }
  }

  public setNext(next: Middleware): void {
    this.nextMiddleware = next;
  }

  private extractMethod(options: RequestInit | undefined): string {
    return options?.method?.toUpperCase() || 'GET';
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
      return 'retry_after';
    }

    // Check for Rate-Limit headers
    const rateLimit = response.headers.get('RateLimit-Limit');
    if (rateLimit) {
      return 'rate_limit';
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

  private extractEndpoint(request: RequestInfo): string {
    try {
      const url = typeof request === 'string' ? request : request.url;
      const urlObj = new URL(url);
      let endpoint = urlObj.pathname.replace(/^\/(v\d+(\.\d+)?|beta)/, '');

      // Apply logging policy to sensitive path segments
      if (this.shouldConcealLogs) {
        endpoint = redactSiteNameFromPath(endpoint); // Process names first
        endpoint = smearSiteIdFromPath(endpoint); // Then GUIDs (more specific match)
      }

      return endpoint || '/';
    } catch {
      return 'unknown';
    }
  }

  private extractStatusCodeFromError(error: unknown): number {
    if (error instanceof GraphError) {
      return error.statusCode || 0;
    }

    if (isGraphApiError(error)) {
      return error.statusCode || error.response?.status || 0;
    }

    return 0;
  }
}
