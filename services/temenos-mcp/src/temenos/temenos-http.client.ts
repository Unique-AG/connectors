import { Injectable, Logger } from '@nestjs/common';
import { isPlainObject, isString } from 'remeda';
import { request } from 'undici';
import { TemenosConfig } from '~/config';
import { Metrics } from './metrics';

export class TemenosApiError extends Error {
  public constructor(
    public readonly status: number,
    public readonly path: string,
    message: string,
  ) {
    super(message);
    this.name = 'TemenosApiError';
  }
}

@Injectable()
export class TemenosHttpClient {
  private readonly logger = new Logger(TemenosHttpClient.name);

  public constructor(
    private readonly config: TemenosConfig,
    private readonly metrics: Metrics,
  ) {}

  public async get<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
    const url = this.buildUrl(path, params);
    const start = Date.now();

    this.logger.debug({ path }, 'Temenos API call');

    let status = 0;
    try {
      const response = await request(url, {
        method: 'GET',
        headers: {
          apikey: this.config.apiKey.value,
          Accept: 'application/json',
        },
      });

      status = response.statusCode;
      const rawBody = await response.body.text();
      const responseBody = this.tryParseJson(rawBody);

      if (status >= 400) {
        const message = this.extractErrorMessage(responseBody, status, rawBody);
        throw new TemenosApiError(status, path, message);
      }

      return responseBody as T;
    } catch (err) {
      this.logger.error({ path, status, err }, 'Temenos API request failed');
      throw err;
    } finally {
      this.metrics.recordApiRequest({ path, status, durationMs: Date.now() - start });
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
      const message =
        this.getStringField(body, 'message') ??
        this.getStringField(body, 'detail') ??
        this.getStringField(body, 'title') ??
        this.getStringField(body, 'error');
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
