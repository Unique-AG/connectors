import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { Client, Dispatcher } from 'undici';
import { Config } from '../../config';
import { normalizeError } from '../../utils/normalize-error';
import { UniqueAuthService } from '../unique-auth.service';

@Injectable()
export class IngestionHttpClient implements OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly limiter: Bottleneck;
  private readonly httpClient: Client;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    const ingestionServiceBaseUrl = this.configService.get('unique.ingestionServiceBaseUrl', {
      infer: true,
    });
    this.httpClient = new Client(ingestionServiceBaseUrl, {
      bodyTimeout: 30000,
      headersTimeout: 30000,
    });

    const apiRateLimitPerMinute = this.configService.get('unique.apiRateLimitPerMinute', {
      infer: true,
    });
    this.limiter = new Bottleneck({
      reservoir: apiRateLimitPerMinute,
      reservoirRefreshAmount: apiRateLimitPerMinute,
      reservoirRefreshInterval: 60_000,
    });
  }

  public async onModuleDestroy(): Promise<void> {
    await this.httpClient.close();
  }

  public async request(
    options: Dispatcher.RequestOptions & { headers?: Record<string, string> },
  ): Promise<Dispatcher.ResponseData> {
    return await this.limiter.schedule(async () => {
      try {
        return await this.httpClient.request({
          ...options,
          headers: {
            ...options.headers,
            ...(await this.getHeaders()),
          },
        });
      } catch (error) {
        this.logger.error({
          msg: `Failed ingestion HTTP request: ${normalizeError(error).message}`,
          error,
        });
        throw error;
      }
    });
  }

  private async getHeaders(): Promise<Record<string, string>> {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    const clientExtraHeaders =
      uniqueConfig.serviceAuthMode === 'cluster_local'
        ? { 'x-service-id': 'sharepoint-connector', ...uniqueConfig.serviceExtraHeaders }
        : { Authorization: `Bearer ${await this.uniqueAuthService.getToken()}` };

    return {
      ...clientExtraHeaders,
      'Content-Type': 'application/json',
    };
  }
}
