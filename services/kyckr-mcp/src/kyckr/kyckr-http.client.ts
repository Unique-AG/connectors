import { Injectable, Logger } from '@nestjs/common';
import { isPlainObject, isString } from 'remeda';
import { Agent, type Dispatcher, request } from 'undici';
import { KyckrConfig } from '~/config';
import { Metrics } from './metrics';

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

export class KyckrRateLimitError extends KyckrApiError {
  public constructor(
    path: string,
    public readonly retryAfterSeconds: number | undefined,
  ) {
    const hint = retryAfterSeconds !== undefined ? ` Retry after ${retryAfterSeconds}s.` : '';
    super(429, path, `Rate limit exceeded.${hint}`);
    this.name = 'KyckrRateLimitError';
  }
}

@Injectable()
export class KyckrHttpClient {
  private static readonly MAX_RESPONSE_BYTES = 10 * 1024 * 1024;

  private static readonly dispatcher = new Agent({
    headersTimeout: 30_000,
    bodyTimeout: 60_000,
  });

  private readonly logger = new Logger(KyckrHttpClient.name);

  public constructor(
    private readonly config: KyckrConfig,
    private readonly metrics: Metrics,
  ) {}

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
        dispatcher: KyckrHttpClient.dispatcher,
      });

      status = response.statusCode;

      if (status === 429) {
        response.body.destroy();
        throw new KyckrRateLimitError(path, this.parseRetryAfter(response.headers['retry-after']));
      }

      const rawBody = await this.readBodyWithLimit(
        response.body,
        KyckrHttpClient.MAX_RESPONSE_BYTES,
      );
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
      const durationMs = Date.now() - start;
      this.metrics.recordApiRequest({
        method,
        path: this.normalizePath(path),
        status,
        durationMs,
      });
    }
  }

  private async readBodyWithLimit(
    body: Dispatcher.ResponseData['body'],
    maxBytes: number,
  ): Promise<string> {
    let total = 0;
    const chunks: Buffer[] = [];
    for await (const chunk of body) {
      const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      total += buf.length;
      if (total > maxBytes) {
        throw new Error(`Kyckr response exceeded ${maxBytes} bytes`);
      }
      chunks.push(buf);
    }
    return Buffer.concat(chunks).toString('utf-8');
  }

  private parseRetryAfter(header: string | string[] | undefined): number | undefined {
    const raw = Array.isArray(header) ? header[0] : header;
    if (!raw) {
      return undefined;
    }
    const seconds = Number.parseInt(raw, 10);
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined;
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
    [/^\/orders\/[^/]+\/download$/, '/orders/:orderId/download'],
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
