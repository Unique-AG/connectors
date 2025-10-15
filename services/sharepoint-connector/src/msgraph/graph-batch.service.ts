import { Client } from '@microsoft/microsoft-graph-client';
import type { Drive } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { Config } from '../config';
import { normalizeError } from '../utils/normalize-error';
import { GraphClientFactory } from './graph-client.factory';
import type {
  BatchError,
  BatchRequest,
  BatchRequestPayload,
  BatchResponse,
  BatchResponsePayload,
  BatchResult,
  DriveItemsResponse,
} from './types/batch.types';

@Injectable()
export class GraphBatchService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly graphClient: Client;
  private readonly limiter: Bottleneck;
  private readonly maxBatchSize = 20;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.graphClient = this.graphClientFactory.createClient();

    const msGraphRateLimitPer10Seconds = this.configService.get(
      'sharepoint.graphRateLimitPer10Seconds',
      { infer: true },
    );

    this.limiter = new Bottleneck({
      reservoir: msGraphRateLimitPer10Seconds,
      reservoirRefreshAmount: msGraphRateLimitPer10Seconds,
      reservoirRefreshInterval: 10000,
    });
  }

  public async executeBatch<T = unknown>(requests: BatchRequest[]): Promise<BatchResult<T>[]> {
    if (requests.length === 0) {
      return [];
    }

    if (requests.length > this.maxBatchSize) {
      return await this.executeBatchesInChunks<T>(requests);
    }

    return await this.executeSingleBatch<T>(requests);
  }

  public async fetchSiteMetadata(siteId: string): Promise<{
    webUrl: string;
    drives: Drive[];
  }> {
    const requests: BatchRequest[] = [
      {
        id: 'site',
        method: 'GET',
        url: `/sites/${siteId}?$select=webUrl`,
      },
      {
        id: 'drives',
        method: 'GET',
        url: `/sites/${siteId}/drives`,
      },
    ];

    const results = await this.executeBatch(requests);

    const siteResult = results.find((r) => r.data && 'id' in (r.data as object) && (r.data as { id: string }).id === 'site');
    const drivesResult = results.find((r) => r.data && 'id' in (r.data as object) && (r.data as { id: string }).id === 'drives');

    if (!siteResult?.success || !drivesResult?.success) {
      const failedRequest = !siteResult?.success ? 'site' : 'drives';
      throw new Error(`Failed to fetch ${failedRequest} metadata: ${siteResult?.error?.message || drivesResult?.error?.message}`);
    }

    const siteData = siteResult.data as { body: { webUrl: string } };
    const drivesData = drivesResult.data as { body: { value: Drive[] } };

    return {
      webUrl: siteData.body.webUrl,
      drives: drivesData.body.value || [],
    };
  }

  public async fetchMultipleFolderChildren(
    requests: Array<{ driveId: string; itemId: string; selectFields: string[] }>,
  ): Promise<Map<string, DriveItemsResponse>> {
    const batchRequests: BatchRequest[] = requests.map((req, index) => {
      const selectQuery = req.selectFields.join(',');
      return {
        id: `${index}`,
        method: 'GET',
        url: `/drives/${req.driveId}/items/${req.itemId}/children?$select=${selectQuery}&$expand=listItem($expand=fields)`,
      };
    });

    const results = await this.executeBatch<DriveItemsResponse>(batchRequests);
    const resultMap = new Map<string, DriveItemsResponse>();

    for (let i = 0; i < requests.length; i++) {
      const result = results[i];
      const request = requests[i];
      
      if (!result || !request) {
        continue;
      }

      const key = `${request.driveId}:${request.itemId}`;

      if (result.success && result.data) {
        const responseData = result.data as unknown as { body: DriveItemsResponse };
        resultMap.set(key, responseData.body);
      } else {
        this.logger.warn(
          `Failed to fetch children for ${key}: ${result.error?.message || 'Unknown error'}`,
        );
        resultMap.set(key, { value: [] });
      }
    }

    return resultMap;
  }

  private async executeSingleBatch<T>(requests: BatchRequest[]): Promise<BatchResult<T>[]> {
    const batchPayload: BatchRequestPayload = { requests };

    try {
      const response = await this.makeRateLimitedRequest<BatchResponsePayload>(() =>
        this.graphClient.api('/$batch').post(batchPayload),
      );

      return this.parseBatchResponse<T>(response, requests);
    } catch (error) {
      this.logger.error({
        msg: 'Batch request failed',
        error: normalizeError(error),
        requestCount: requests.length,
      });

      return requests.map((req) => ({
        success: false,
        status: 500,
        error: {
          code: 'BatchRequestFailed',
          message: normalizeError(error).message,
        },
        data: { id: req.id } as T,
      }));
    }
  }

  private async executeBatchesInChunks<T>(requests: BatchRequest[]): Promise<BatchResult<T>[]> {
    const chunks: BatchRequest[][] = [];
    for (let i = 0; i < requests.length; i += this.maxBatchSize) {
      chunks.push(requests.slice(i, i + this.maxBatchSize));
    }

    this.logger.debug(
      `Splitting ${requests.length} requests into ${chunks.length} batches of max ${this.maxBatchSize}`,
    );

    const results = await Promise.all(chunks.map((chunk) => this.executeSingleBatch<T>(chunk)));

    return results.flat();
  }

  private parseBatchResponse<T>(
    response: BatchResponsePayload,
    originalRequests: BatchRequest[],
  ): BatchResult<T>[] {
    const results: BatchResult<T>[] = [];

    for (const batchResponse of response.responses) {
      const result = this.parseIndividualResponse<T>(batchResponse);
      results.push(result);
    }

    if (results.length !== originalRequests.length) {
      this.logger.warn(
        `Batch response count mismatch: expected ${originalRequests.length}, got ${results.length}`,
      );
    }

    return results;
  }

  private parseIndividualResponse<T>(response: BatchResponse): BatchResult<T> {
    const isSuccess = response.status >= 200 && response.status < 300;

    if (isSuccess) {
      return {
        success: true,
        status: response.status,
        data: { id: response.id, body: response.body } as T,
      };
    }

    const error = response.body as BatchError;
    return {
      success: false,
      status: response.status,
      error: error || {
        code: 'UnknownError',
        message: `Request failed with status ${response.status}`,
      },
      data: { id: response.id } as T,
    };
  }

  private async makeRateLimitedRequest<T>(requestFn: () => Promise<T>): Promise<T> {
    return await this.limiter.schedule(async () => await requestFn());
  }
}

