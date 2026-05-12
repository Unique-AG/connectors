import { Injectable, Logger } from '@nestjs/common';
import { MetricService } from 'nestjs-otel';
import { isPlainObject, isString } from 'remeda';
import { request } from 'undici';
import { KyckrConfig } from '~/config';

export class KyckrApiError extends Error {
  public constructor(
    public readonly status: number,
    public readonly path: string,
    message: string,
    public readonly correlationId?: string,
  ) {
    super(message);
    this.name = 'KyckrApiError';
  }
}

@Injectable()
export class KyckrHttpClient {
  private readonly logger = new Logger(KyckrHttpClient.name);
  private readonly requestCounter;
  private readonly requestDuration;

  public constructor(
    private readonly config: KyckrConfig,
    metricService: MetricService,
  ) {
    this.requestCounter = metricService.getCounter('kyckr_api_requests_total', {
      description: 'Total Kyckr API requests',
    });
    this.requestDuration = metricService.getHistogram('kyckr_api_request_duration_ms', {
      description: 'Kyckr API request duration in milliseconds',
    });
  }

  public async get<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
    return this.call<T>('GET', path, params);
  }

  public async post<T>(path: string, body: unknown): Promise<T> {
    return this.call<T>('POST', path, undefined, body);
  }

  private async call<T>(
    method: string,
    path: string,
    params?: Record<string, string | undefined>,
    body?: unknown,
  ): Promise<T> {
    const url = this.buildUrl(path, params);
    const start = Date.now();

    this.logger.debug({ method, path }, 'Kyckr API call');

    let status = 0;
    try {
      const response = await request(url, {
        method,
        headers: {
          Authorization: `Bearer ${this.config.apiKey.value}`,
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });

      status = response.statusCode;
      const rawBody = await response.body.text();
      const responseBody = this.tryParseJson(rawBody);

      if (status >= 400) {
        const correlationId = this.getStringField(responseBody, 'correlationId');
        const message = this.extractErrorMessage(responseBody, status, rawBody);
        throw new KyckrApiError(status, path, message, correlationId);
      }

      return responseBody as T;
    } catch (err) {
      this.logger.error({ method, path, status, err }, 'Kyckr API request failed');
      throw err;
    } finally {
      const duration = Date.now() - start;
      this.requestCounter.add(1, {
        method,
        path: this.normalizePath(path),
        status: String(status),
      });
      this.requestDuration.record(duration, { method, path: this.normalizePath(path) });
    }
  }

  private buildUrl(path: string, params?: Record<string, string | undefined>): string {
    const url = new URL(`${this.config.apiBaseUrl}${path}`);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined) {
          url.searchParams.set(key, value);
        }
      }
    }
    return url.toString();
  }

  private static readonly ROUTE_PATTERNS: [RegExp, string][] = [
    [/^\/companies\/[^/]+\/enhanced$/, '/companies/:kyckrId/enhanced'],
    [/^\/companies\/[^/]+\/lite$/, '/companies/:kyckrId/lite'],
    [/^\/companies\/[^/]+\/documents$/, '/companies/:kyckrId/documents'],
    [/^\/companies$/, '/companies'],
    [/^\/orders\/[^/]+$/, '/orders/:orderId'],
    [/^\/orders$/, '/orders'],
  ];

  private normalizePath(path: string): string {
    for (const [pattern, template] of KyckrHttpClient.ROUTE_PATTERNS) {
      if (pattern.test(path)) {
        return template;
      }
    }
    this.logger.warn({ path }, 'Unknown Kyckr API path - metric label not normalized');
    return '[unknown]';
  }

  private tryParseJson(raw: string): unknown {
    if (!raw) {
      return undefined;
    }
    try {
      return JSON.parse(raw);
    } catch {
      return undefined;
    }
  }

  private extractErrorMessage(body: unknown, status: number, raw: string): string {
    if (isPlainObject(body)) {
      // Kyckr's ProblemDetails errors live under `data`, not at the top level.
      const data = isPlainObject(body.data) ? body.data : undefined;

      const message =
        this.getStringField(data, 'detail') ??
        this.getStringField(data, 'title') ??
        this.getStringField(data, 'type') ??
        this.getStringField(body, 'message') ??
        this.getStringField(body, 'detail') ??
        this.getStringField(body, 'title') ??
        this.getStringField(body, 'details');

      if (message) {
        return message;
      }
    }
    const trimmed = raw.trim();
    if (trimmed) {
      return trimmed.length > 200 ? `${trimmed.slice(0, 200)}...` : trimmed;
    }
    return `HTTP ${status}`;
  }

  private getStringField(object: unknown, key: string): string | undefined {
    if (isPlainObject(object)) {
      const value = object[key];
      return isString(value) ? value : undefined;
    }
    return undefined;
  }
}
