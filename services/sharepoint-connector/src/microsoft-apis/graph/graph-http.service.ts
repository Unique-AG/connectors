import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Counter, type Histogram } from '@opentelemetry/api';
import { Agent, type Dispatcher, interceptors } from 'undici';
import type { Config } from '../../config';
import {
  SPC_MS_GRAPH_API_REQUEST_DURATION_SECONDS,
  SPC_MS_GRAPH_API_SLOW_REQUESTS_TOTAL,
  SPC_MS_GRAPH_API_THROTTLE_EVENTS_TOTAL,
} from '../../metrics';
import { shouldConcealLogs } from '../../utils/logging.util';
import { MicrosoftAuthenticationService } from '../auth/microsoft-authentication.service';
import { createGraphLoggingInterceptor } from './interceptors/logging.interceptor';
import { createGraphMetricsInterceptor } from './interceptors/metrics.interceptor';
import { createGraphTokenRefreshInterceptor } from './interceptors/token-refresh.interceptor';
import type { GraphApiResponse } from './types/sharepoint.types';

const GRAPH_API_BASE_URL = 'https://graph.microsoft.com';

export interface GraphRequestOptions {
  apiVersion?: 'v1.0' | 'beta';
  select?: string | string[];
  expand?: string;
  top?: number;
}

interface GraphErrorResponse {
  error?: {
    code?: string;
    message?: string;
    innerError?: {
      code?: string;
      'request-id'?: string;
      date?: string;
    };
  };
}

export class GraphHttpError extends Error {
  public constructor(
    message: string,
    public readonly statusCode: number,
    public readonly code?: string,
    public readonly requestId?: string,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = 'GraphHttpError';
  }
}

@Injectable()
export class GraphHttpService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly agent: Dispatcher;
  private readonly shouldConcealLogs: boolean;
  private readonly msTenantId: string;

  public constructor(
    private readonly microsoftAuthenticationService: MicrosoftAuthenticationService,
    private readonly configService: ConfigService<Config, true>,
    @Inject(SPC_MS_GRAPH_API_REQUEST_DURATION_SECONDS)
    private readonly spcGraphApiRequestDurationSeconds: Histogram,
    @Inject(SPC_MS_GRAPH_API_THROTTLE_EVENTS_TOTAL)
    private readonly spcGraphApiThrottleEventsTotal: Counter,
    @Inject(SPC_MS_GRAPH_API_SLOW_REQUESTS_TOTAL)
    private readonly spcGraphApiSlowRequestsTotal: Counter,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
    this.msTenantId = this.configService.get('sharepoint.authTenantId', { infer: true });

    // Using Agent instead of Client allows cross-origin redirects (e.g., Graph API → SharePoint).
    // Per Fetch spec, Authorization header is automatically stripped on cross-origin redirects,
    // which is exactly what we need since SharePoint download URLs have their own auth (tempauth).
    const httpAgent = new Agent({
      bodyTimeout: 60_000,
      headersTimeout: 30_000,
      connectTimeout: 15_000,
    });

    const interceptorsInCallingOrder = [
      interceptors.redirect({ maxRedirections: 10 }),
      interceptors.retry({
        maxRetries: 4,
        minTimeout: 1_000,
        statusCodes: [429, 500, 502, 503, 504],
        errorCodes: [
          'ECONNRESET',
          'ECONNREFUSED',
          'ENOTFOUND',
          'ENETDOWN',
          'ENETUNREACH',
          'EHOSTDOWN',
          'EHOSTUNREACH',
          'EPIPE',
          'UND_ERR_SOCKET',
        ],
      }),
      createGraphTokenRefreshInterceptor(async () =>
        this.microsoftAuthenticationService.getAccessToken('graph'),
      ),
      createGraphMetricsInterceptor(
        this.spcGraphApiRequestDurationSeconds,
        this.spcGraphApiThrottleEventsTotal,
        this.spcGraphApiSlowRequestsTotal,
        this.msTenantId,
      ),
      createGraphLoggingInterceptor(this.shouldConcealLogs),
    ];

    this.agent = httpAgent.compose(interceptorsInCallingOrder.reverse());
  }

  public async get<T>(endpoint: string, options: GraphRequestOptions = {}): Promise<T> {
    const { apiVersion = 'v1.0' } = options;
    const path = this.buildPath(endpoint, apiVersion, options);
    const token = await this.microsoftAuthenticationService.getAccessToken('graph');

    const { statusCode, body } = await this.agent.request({
      origin: GRAPH_API_BASE_URL,
      method: 'GET',
      path,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
      },
    });

    if (statusCode >= 400) {
      await this.handleErrorResponse(statusCode, body, path);
    }

    return body.json() as Promise<T>;
  }

  public async getStream(endpoint: string, options: GraphRequestOptions = {}): Promise<Buffer> {
    const { apiVersion = 'v1.0' } = options;
    const path = this.buildPath(endpoint, apiVersion, options);
    const token = await this.microsoftAuthenticationService.getAccessToken('graph');

    // Agent (unlike Client) can follow cross-origin redirects (e.g., to SharePoint download URLs).
    // Per Fetch spec, Authorization header is automatically stripped on cross-origin redirects.
    const { statusCode, body } = await this.agent.request({
      origin: GRAPH_API_BASE_URL,
      method: 'GET',
      path,
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (statusCode >= 400) {
      await this.handleErrorResponse(statusCode, body, path);
    }

    const chunks: Buffer[] = [];
    for await (const chunk of body) {
      chunks.push(Buffer.from(chunk));
    }

    return Buffer.concat(chunks);
  }

  public async paginate<T>(endpoint: string, options: GraphRequestOptions = {}): Promise<T[]> {
    const allItems: T[] = [];
    let nextPath: string | undefined = this.buildPath(
      endpoint,
      options.apiVersion ?? 'v1.0',
      options,
    );

    while (nextPath) {
      const token = await this.microsoftAuthenticationService.getAccessToken('graph');

      const { statusCode, body } = await this.agent.request({
        origin: GRAPH_API_BASE_URL,
        method: 'GET',
        path: nextPath,
        headers: {
          Accept: 'application/json',
          Authorization: `Bearer ${token}`,
        },
      });

      if (statusCode >= 400) {
        await this.handleErrorResponse(statusCode, body, nextPath);
      }

      const response = (await body.json()) as GraphApiResponse<T>;
      const items = response?.value || [];
      allItems.push(...items);

      if (response['@odata.nextLink']) {
        const url = new URL(response['@odata.nextLink']);
        const pathWithSearch = url.pathname + url.search;
        // Strip API version prefix (e.g., /v1.0/ or /beta/) to avoid double prefixing
        nextPath = pathWithSearch.replace(/^\/(v\d+\.\d+|beta)\//, '');
      } else {
        nextPath = undefined;
      }
    }

    return allItems;
  }

  private buildPath(endpoint: string, apiVersion: string, options: GraphRequestOptions): string {
    const cleanEndpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;
    const basePath = `/${apiVersion}/${cleanEndpoint}`;

    const queryParams = new URLSearchParams();

    if (options.select) {
      const selectValue = Array.isArray(options.select) ? options.select.join(',') : options.select;
      queryParams.set('$select', selectValue);
    }

    if (options.expand) {
      queryParams.set('$expand', options.expand);
    }

    if (options.top) {
      queryParams.set('$top', String(options.top));
    }

    const queryString = queryParams.toString();
    return queryString ? `${basePath}?${queryString}` : basePath;
  }

  private async handleErrorResponse(
    statusCode: number,
    body: Dispatcher.ResponseData['body'],
    path: string,
  ): Promise<never> {
    let errorBody: GraphErrorResponse | undefined;
    let rawBody: string | undefined;

    try {
      rawBody = await body.text();
      errorBody = JSON.parse(rawBody) as GraphErrorResponse;
    } catch {
      // Body might not be JSON
    }

    const message =
      errorBody?.error?.message || `Graph API request failed with status ${statusCode}`;
    const code = errorBody?.error?.code;
    const requestId = errorBody?.error?.innerError?.['request-id'];

    this.logger.error({
      msg: 'Graph API request failed',
      path,
      statusCode,
      code,
      requestId,
      errorBody: rawBody,
    });

    throw new GraphHttpError(message, statusCode, code, requestId, errorBody);
  }
}
