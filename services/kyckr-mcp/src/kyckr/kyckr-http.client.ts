import { Injectable, Logger } from '@nestjs/common';
import { MetricService } from 'nestjs-otel';
import { request } from 'undici';
import { KyckrConfig } from '../config';

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
        const correlationId = this.extractCorrelationId(responseBody);
        const message = this.extractErrorMessage(responseBody, status, rawBody);
        this.logger.error({ method, path, status, correlationId }, `Kyckr API error: ${message}`);
        throw new KyckrApiError(status, path, message, correlationId);
      }

      return responseBody as T;
    } catch (err) {
      if (err instanceof KyckrApiError) {
        throw err;
      }
      this.logger.error({ method, path, err }, 'Kyckr API request failed');
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

  private normalizePath(path: string): string {
    return path.replace(/\/[A-Za-z0-9_-]{8,}/g, '/:id');
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

  private extractCorrelationId(body: unknown): string | undefined {
    if (body && typeof body === 'object' && 'correlationId' in body) {
      return String((body as Record<string, unknown>).correlationId);
    }
    return undefined;
  }

  private extractErrorMessage(body: unknown, status: number, raw: string): string {
    if (body && typeof body === 'object') {
      const b = body as Record<string, unknown>;
      if (typeof b.message === 'string') {
        return b.message;
      }
      if (typeof b.detail === 'string') {
        return b.detail;
      }
      if (typeof b.title === 'string') {
        return b.title;
      }
    }
    const trimmed = raw.trim();
    if (trimmed) {
      return trimmed.length > 200 ? `${trimmed.slice(0, 200)}…` : trimmed;
    }
    return `HTTP ${status}`;
  }
}
