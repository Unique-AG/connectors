import assert from 'node:assert';
import { randomUUID } from 'node:crypto';
import { Inject, Injectable } from '@nestjs/common';
import { chunk, identity } from 'remeda';
import { Client, Dispatcher, interceptors } from 'undici';
import { SHAREPOINT_REST_HTTP_CLIENT } from '../../http-client.tokens';
import { MicrosoftAuthenticationService } from '../auth/microsoft-authentication.service';
import { createTokenRefreshInterceptor } from './token-refresh.interceptor';

@Injectable()
export class SharepointRestHttpService {
  private readonly client: Dispatcher;

  public constructor(
    @Inject(SHAREPOINT_REST_HTTP_CLIENT) httpClient: Client,
    private readonly microsoftAuthenticationService: MicrosoftAuthenticationService,
  ) {
    // TODO: Add metrics middleware with some logging once we start implementing proper metrics
    // TODO: Add middleware that logs the request headers and body on debug level
    const interceptorsInCallingOrder = [
      interceptors.redirect({
        maxRedirections: 10,
      }),
      interceptors.retry({
        maxRetries: 3,
      }),
      createTokenRefreshInterceptor(async () =>
        this.microsoftAuthenticationService.getAccessToken('sharepoint-rest'),
      ),
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
      `Failed to request SharePoint endpoint ${path}: ${statusCode}`,
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
    const chunkedApiPaths = chunk(apiPaths, 20);
    for (const apiPathsChunk of chunkedApiPaths) {
      const boundary = `batch_${randomUUID()}`;
      const batchItems = apiPathsChunk
        .map((apiPath) => (apiPath.startsWith('/') ? apiPath.slice(1) : apiPath))
        .map((apiPath) => `/sites/${siteName}/_api/web/${apiPath}`)
        .map((apiPath) => this.buildBatchItem(apiPath, boundary));

      const requestBody = `${batchItems.join('\r\n\r\n')}\r\n--${boundary}--\r\n`;
      const path = `/sites/${siteName}/_api/$batch`;
      const { statusCode, body, headers } = await this.client.request({
        method: 'POST',
        path,
        headers: {
          'Content-Type': `multipart/mixed; boundary=${boundary}`,
          Authorization: `Bearer ${token}`,
        },
        body: requestBody,
      });

      assert.ok(
        200 <= statusCode && statusCode < 300,
        `Failed to request SharePoint batch endpoint ${path}: ${statusCode}`,
      );

      // Example: multipart/mixed; boundary=batchresponse_a1182996-c482-49d1-ac38-16ae3788d990
      const responseBoundary = headers['content-type']?.toString().split(';')[1]?.split('=')[1];
      assert.ok(responseBoundary, 'Response boundary not found');
      const responseBody = await body.text();
      const responsesChunk = responseBody
        .split(`--${responseBoundary}`)
        .slice(1, -1)
        .map((singleResponse) => {
          const lines = singleResponse.split('\r\n').filter(identity());
          const responseCodeLine = lines.find((line) => line.startsWith('HTTP/1.1'));
          const statusCode = Number(responseCodeLine?.split(' ')[1]);
          const responseLine = lines[lines.length - 1];
          // TODO: Add proper handling for retrying on 429 / 5XX errors
          // TODO: Add some errors handling in general - currently we just swallow errors
          return statusCode === 200 ? JSON.parse(responseLine ?? '{}') : {};
        });
      responses.push(...responsesChunk);
    }

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
