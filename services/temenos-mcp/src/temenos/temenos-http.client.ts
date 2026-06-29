import { Injectable, Logger } from '@nestjs/common';
import { isPlainObject, isString } from 'remeda';
import { type Dispatcher, request } from 'undici';
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
  // Hard cap on upstream response size. Temenos paginates (default 99 records),
  // so legitimate bodies stay well under this. The cap stops attacker-controlled
  // paging from forcing unbounded heap allocation.
  private static readonly MAX_RESPONSE_BYTES = 10 * 1024 * 1024;

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
      const rawBody = await this.readBodyWithLimit(
        response.body,
        TemenosHttpClient.MAX_RESPONSE_BYTES,
      );
      const responseBody = this.tryParseJson(rawBody);

      if (status >= 400) {
        const message = this.extractErrorMessage(responseBody, status);
        throw new TemenosApiError(status, path, message);
      }

      return responseBody as T;
    } catch (err) {
      // Log only the error class + message, never the full error object. The
      // message is sourced from a documented Temenos error envelope field; raw
      // upstream bodies are dropped in extractErrorMessage so they can't reach
      // the log as a side channel for customer/account details.
      const errorName = err instanceof Error ? err.name : 'unknown';
      const errorMessage = err instanceof Error ? err.message : String(err);
      this.logger.error({ path, status, errorName, errorMessage }, 'Temenos API request failed');
      throw err;
    } finally {
      this.metrics.recordApiRequest({ path, status, durationMs: Date.now() - start });
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
        throw new Error(`Temenos response exceeded ${maxBytes} bytes`);
      }
      chunks.push(buf);
    }
    return Buffer.concat(chunks).toString('utf-8');
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

  private extractErrorMessage(body: unknown, status: number): string {
    // Only surface text from documented Temenos error-envelope fields. Falling
    // back to the raw body would echo arbitrary upstream content into errors
    // (and logs), which is a PII leak risk on responses containing customer
    // or account details.
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
