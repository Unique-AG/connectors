import assert from 'node:assert';
import { randomUUID } from 'node:crypto';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { chunk, identity } from 'remeda';
import { Client, Dispatcher, interceptors } from 'undici';
import { Config } from '../../config';
import { redact, shouldConcealLogs } from '../../utils/logging.util';
import { MicrosoftAuthenticationService } from '../auth/microsoft-authentication.service';
import { createLoggingInterceptor } from './logging.interceptor';
import { createTokenRefreshInterceptor } from './token-refresh.interceptor';

const BATCH_SIZE = 20;

@Injectable()
export class SharepointRestHttpService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly client: Dispatcher;
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly microsoftAuthenticationService: MicrosoftAuthenticationService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
    const sharePointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
    const httpClient = new Client(sharePointBaseUrl, {
      bodyTimeout: 60_000,
      headersTimeout: 30_000,
      connectTimeout: 15_000,
    });

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
        // We retry on POST because batch endpoint is using POST method. We are not supposed to do
        // any modifications on SharePoint so all called endpoints should be safe to retry,
        // requestSingle is not even allowing non-GET requests at this time.
        methods: ['GET', 'POST'],
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
    this.client = httpClient.compose(interceptorsInCallingOrder.reverse());
  }

  // Call a single SharePoint REST API endpoint and gives back the body as a JSON object.
  public async requestSingle<T>(siteName: string, apiPath: string): Promise<T> {
    const token = await this.microsoftAuthenticationService.getAccessToken('sharepoint-rest');
    const cleanedApiPath = apiPath.startsWith('/') ? apiPath.slice(1) : apiPath;
    const path = `/sites/${siteName}/_api/${cleanedApiPath}`;
    const { statusCode, body } = await this.client.request({
      method: 'GET',
      path,
      headers: {
        'Content-Type': 'application/json;odata=nometadata',
        Accept: 'application/json;odata=nometadata',
        Authorization: `Bearer ${token}`,
      },
    });

    assert.ok(
      200 <= statusCode && statusCode < 300,
      `Failed to request SharePoint endpoint ${this.shouldConcealLogs ? path.replace(siteName, redact(siteName)) : path}: ${statusCode}`,
    );

    return body.json() as Promise<T>;
  }

  // Uses /$batch endpoint to split calls provided into apiPaths into multiple requests batched by
  // 20 requests at a time.
  // It is built to typings-wise support multiple calls to the same endpoint, mixing responses is
  // not possible to type.
  public async requestBatch<T>(siteName: string, apiPaths: string[]): Promise<T[]> {
    const token = await this.microsoftAuthenticationService.getAccessToken('sharepoint-rest');
    const responses: T[] = [];
    const chunkedApiPaths = chunk(apiPaths, BATCH_SIZE);

    this.logger.debug({
      msg: 'Starting SharePoint batch request',
      siteName: this.shouldConcealLogs ? redact(siteName) : siteName,
      totalPaths: apiPaths.length,
      batchChunks: chunkedApiPaths.length,
    });

    for (const [chunkIndex, apiPathsChunk] of chunkedApiPaths.entries()) {
      const boundary = `batch_${randomUUID()}`;
      const fullApiPaths = apiPathsChunk
        .map((apiPath) => (apiPath.startsWith('/') ? apiPath.slice(1) : apiPath))
        .map((apiPath) => `/sites/${siteName}/_api/web/${apiPath}`);
      const batchItems = fullApiPaths.map((apiPath) => this.buildBatchItem(apiPath, boundary));

      const redactedApiPaths = this.shouldConcealLogs
        ? fullApiPaths.map((path) => path.replace(siteName, redact(siteName)))
        : fullApiPaths;

      this.logger.debug({
        msg: 'Executing batch chunk',
        chunkIndex: chunkIndex + 1,
        totalChunks: chunkedApiPaths.length,
        pathsInChunk: fullApiPaths.length,
        paths: redactedApiPaths,
      });

      const requestBody = `${batchItems.join('\r\n\r\n')}\r\n--${boundary}--\r\n`;
      const path = `/sites/${siteName}/_api/$batch`;

      const requestStartTime = Date.now();
      const { statusCode, body, headers } = await this.client.request({
        method: 'POST',
        path,
        headers: {
          'Content-Type': `multipart/mixed; boundary=${boundary}`,
          Authorization: `Bearer ${token}`,
        },
        body: requestBody,
      });

      const duration = Date.now() - requestStartTime;
      const isSuccess = 200 <= statusCode && statusCode < 300;

      if (!isSuccess) {
        const redactedPath = this.shouldConcealLogs
          ? path.replace(siteName, redact(siteName))
          : path;

        const errorBody = await body.text();
        this.logger.error({
          msg: 'Failed to request SharePoint batch endpoint',
          path: redactedPath,
          chunkIndex: chunkIndex + 1,
          paths: redactedApiPaths,
          statusCode,
          duration,
          errorBody,
        });
        assert.fail(
          `Failed to request SharePoint batch endpoint: Code: ${statusCode}. Response: ${errorBody}`,
        );
      }

      // Example: multipart/mixed; boundary=batchresponse_a1182996-c482-49d1-ac38-16ae3788d990
      const responseBoundary = headers['content-type']?.toString().split(';')[1]?.split('=')[1];
      assert.ok(responseBoundary, 'Response boundary not found');
      const responseBody = await body.text();
      const responsesChunk = responseBody
        .split(`--${responseBoundary}`)
        .slice(1, -1)
        .map((singleResponse, index): T => {
          const lines = singleResponse.split('\r\n').filter(identity());
          const responseCodeLine = lines.find((line) => line.startsWith('HTTP/1.1'));
          const statusCode = Number(responseCodeLine?.split(' ')[1]);
          const responseLine = lines[lines.length - 1];
          // TODO: Add proper handling for retrying on 429 / 5XX errors
          // TODO: Add some errors handling in general - currently we just swallow errors
          if (statusCode === 200) {
            return JSON.parse(responseLine ?? '{}');
          }

          this.logger.error({
            msg: 'Non-200 response in batch item',
            path: redactedApiPaths[index],
            statusCode,
            responseCodeLine,
          });
          return assert.fail(`Non-200 response ${responseCodeLine} from Batch Request`);
        });

      this.logger.debug({
        msg: 'Batch chunk completed successfully',
        chunkIndex: chunkIndex + 1,
        pathsInChunk: fullApiPaths.length,
        duration,
      });

      responses.push(...responsesChunk);
    }

    this.logger.debug({
      msg: 'SharePoint batch request completed',
      totalResponses: responses.length,
      totalChunks: chunkedApiPaths.length,
    });

    return responses;
  }

  private buildBatchItem(apiPath: string, boundary: string): string {
    return [
      `--${boundary}`,
      'Content-Type: application/http',
      'Content-Transfer-Encoding: binary',
      '', // Empty line to separate headers from body
      `GET ${apiPath} HTTP/1.1`,
      `Accept: application/json;odata=nometadata`,
      '', // Empty line to separate current batch from the next
    ].join('\r\n');
  }
}
