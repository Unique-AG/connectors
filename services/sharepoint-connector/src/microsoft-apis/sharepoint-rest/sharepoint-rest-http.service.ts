import { Readable } from 'node:stream';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Dispatcher, interceptors, type RetryHandler } from 'undici';
import { Config } from '../../config';
import { ProxyService } from '../../proxy';
import { shouldDiscloseLogs, smearSharepointRestPath } from '../../utils/logging.util';
import { encodeSiteNameForPath, type ManagedPath } from '../../utils/paths.util';
import type { Smeared } from '../../utils/smeared';
import { MicrosoftAuthenticationService } from '../auth/microsoft-authentication.service';
import { createLoggingInterceptor } from './logging.interceptor';
import { extractODataErrorCode } from './odata-error';
import { createTokenRefreshInterceptor } from './token-refresh.interceptor';

interface SharepointRestRequestOptions {
  headersTimeout?: number;
  // Replaces the response status codes the retry interceptor retries for this request.
  retryStatusCodes?: number[];
}

export class SharepointRestError extends Error {
  public constructor(
    message: string,
    public readonly statusCode: number,
    // For example "-2147024860, Microsoft.SharePoint.SPQueryThrottledException".
    public readonly errorCode: string | undefined,
  ) {
    super(message);
    this.name = 'SharepointRestError';
  }
}

export function isListViewThresholdError(error: unknown): boolean {
  return (
    error instanceof SharepointRestError &&
    (error.errorCode?.includes('SPQueryThrottledException') ?? false)
  );
}

@Injectable()
export class SharepointRestHttpService {
  private readonly client: Dispatcher;
  private readonly shouldConcealLogs: boolean;
  private readonly origin: string;

  public constructor(
    private readonly microsoftAuthenticationService: MicrosoftAuthenticationService,
    private readonly configService: ConfigService<Config, true>,
    private readonly proxyService: ProxyService,
  ) {
    this.shouldConcealLogs = !shouldDiscloseLogs(this.configService);
    this.origin = this.configService.get('sharepoint.baseUrl', { infer: true });

    // TODO: Add metrics middleware once we start implementing proper metrics
    const interceptorsInCallingOrder = [
      interceptors.redirect({
        maxRedirections: 10,
      }),
      interceptors.retry({
        // We do lower base retry count and higher min timeout because the ETIMEDOUT error seems to
        // be transient, as we encounter it for only some sites during a single sync.
        maxRetries: 4,
        minTimeout: 3_000,
        errorCodes: [
          // Error that we encounter occasionally on QA when calling SharePoint REST API
          'ETIMEDOUT',
          // Default codes takes from the undici library
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
      createTokenRefreshInterceptor(async () =>
        this.microsoftAuthenticationService.getAccessToken('sharepoint-rest'),
      ),
      createLoggingInterceptor(this.shouldConcealLogs),
    ];
    const baseDispatcher = this.proxyService.getDispatcher({ mode: 'always' });
    this.client = baseDispatcher.compose(interceptorsInCallingOrder.reverse());
  }

  // Call a single SharePoint REST API endpoint and gives back the body as a JSON object.
  // `apiPath` is appended after `/_api/` (it is not prefixed with `web/`).
  public async requestSingle<T>(
    siteName: Smeared,
    managedPath: ManagedPath,
    apiPath: string,
    options: SharepointRestRequestOptions = {},
  ): Promise<T> {
    const { body } = await this.dispatch(this.siteApiPath(siteName, managedPath, apiPath), options);
    return body.json() as Promise<T>;
  }

  public async requestDownload(
    siteName: Smeared,
    managedPath: ManagedPath,
    apiPath: string,
  ): Promise<Readable> {
    const { body } = await this.dispatch(this.siteApiPath(siteName, managedPath, apiPath));
    return Readable.from(body);
  }

  private siteApiPath(siteName: Smeared, managedPath: ManagedPath, apiPath: string): string {
    const cleanedApiPath = apiPath.startsWith('/') ? apiPath.slice(1) : apiPath;
    const encodedSiteName = siteName.transform((value) => encodeSiteNameForPath(value));
    return `/${managedPath}/${encodedSiteName.value}/_api/${cleanedApiPath}`;
  }

  private async dispatch(
    path: string,
    { headersTimeout, retryStatusCodes }: SharepointRestRequestOptions = {},
  ): Promise<{ body: Dispatcher.ResponseData['body'] }> {
    const token = await this.microsoftAuthenticationService.getAccessToken('sharepoint-rest');
    const requestOptions: Dispatcher.RequestOptions & { retryOptions?: RetryHandler.RetryOptions } =
      {
        origin: this.origin,
        method: 'GET',
        path,
        headers: {
          'Content-Type': 'application/json;odata=nometadata',
          Accept: 'application/json;odata=nometadata',
          Authorization: `Bearer ${token}`,
        },
        ...(headersTimeout === undefined ? {} : { headersTimeout }),
        ...(retryStatusCodes === undefined
          ? {}
          : { retryOptions: { statusCodes: retryStatusCodes } }),
      };
    const { statusCode, body } = await this.client.request(requestOptions);

    if (200 <= statusCode && statusCode < 300) {
      return { body };
    }

    const errorCode = extractODataErrorCode(await body.json().catch(() => undefined));
    throw new SharepointRestError(
      `Failed to request SharePoint endpoint ` +
        `${this.shouldConcealLogs ? smearSharepointRestPath(path) : path}: ` +
        `${statusCode}${errorCode ? ` ${errorCode}` : ''}`,
      statusCode,
      errorCode,
    );
  }
}
