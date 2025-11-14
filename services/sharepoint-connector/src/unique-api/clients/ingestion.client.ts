import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { GraphQLClient } from 'graphql-request';
import { Config } from '../../config';
import { normalizeError } from '../../utils/normalize-error';
import { UniqueAuthService } from '../unique-auth.service';

@Injectable()
export class IngestionClient {
  private readonly logger = new Logger(this.constructor.name);
  private readonly graphQlClient: GraphQLClient;
  private readonly limiter: Bottleneck;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    this.graphQlClient = new GraphQLClient(uniqueConfig.ingestionGraphqlUrl, {
      requestMiddleware: async (request) => {
        const clientExtraHeaders =
          uniqueConfig.serviceAuthMode === 'cluster_local'
            ? uniqueConfig.serviceExtraHeaders
            : { Authorization: `Bearer ${await this.uniqueAuthService.getToken()}` };

        return {
          ...request,
          headers: {
            ...request.headers,
            ...clientExtraHeaders,
            'Content-Type': 'application/json',
          },
        };
      },
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

  public async get<T>(callback: (client: GraphQLClient) => Promise<T>): Promise<T> {
    return await this.limiter.schedule(async () => {
      try {
        return await callback(this.graphQlClient);
      } catch (error) {
        this.logger.error({
          msg: `Failed ingestion request: ${normalizeError(error).message}`,
          error,
        });
        throw error;
      }
    });
  }
}
