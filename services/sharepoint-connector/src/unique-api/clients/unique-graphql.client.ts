import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { GraphQLClient } from 'graphql-request';
import { Config } from '../../config';
import { normalizeError } from '../../utils/normalize-error';
import { UniqueAuthService } from '../unique-auth.service';

export const INGESTION_CLIENT = Symbol('INGESTION_CLIENT');
export const SCOPE_MANAGEMENT_CLIENT = Symbol('SCOPE_MANAGEMENT_CLIENT');

export type UniqueGraphqlClientTarget = 'ingestion' | 'scopeManagement';

@Injectable()
export class UniqueGraphqlClient {
  private readonly logger = new Logger(this.constructor.name);
  private readonly graphQlClient: GraphQLClient;
  private readonly limiter: Bottleneck;

  public constructor(
    private readonly clientTarget: UniqueGraphqlClientTarget,
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    const graphqlUrl = uniqueConfig[`${clientTarget}GraphqlUrl`];

    this.graphQlClient = new GraphQLClient(graphqlUrl, {
      requestMiddleware: async (request) => {
        const additionalHeaders = await this.getAdditionalHeaders();

        return {
          ...request,
          headers: {
            ...request.headers,
            ...additionalHeaders,
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
          msg: `Failed ${this.clientTarget} request: ${normalizeError(error).message}`,
          error,
        });
        throw error;
      }
    });
  }

  private async getAdditionalHeaders(): Promise<Record<string, string>> {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    return uniqueConfig.serviceAuthMode === 'cluster_local'
      ? {
          'x-service-id': 'sharepoint-connector',
          ...uniqueConfig.serviceExtraHeaders,
        }
      : { Authorization: `Bearer ${await this.uniqueAuthService.getToken()}` };
  }
}
