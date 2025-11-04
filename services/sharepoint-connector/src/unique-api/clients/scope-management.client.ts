import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { GraphQLClient } from 'graphql-request';
import { Config } from '../../config';
import { normalizeError } from '../../utils/normalize-error';
import { UniqueAuthService } from '../unique-auth.service';

@Injectable()
export class ScopeManagementClient {
  private readonly logger = new Logger(this.constructor.name);
  private readonly graphQlClient: GraphQLClient;
  private readonly limiter: Bottleneck;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    const clientUrl = this.configService.get('unique.scopeManagementGraphqlUrl', { infer: true });
    const clientHeaders = this.configService.get('unique.httpExtraHeaders', { infer: true });
    this.graphQlClient = new GraphQLClient(clientUrl, {
      headers: {
        ...clientHeaders,
        'Content-Type': 'application/json',
      },
      requestMiddleware: async (request) => {
        return {
          ...request,
          headers: {
            ...request.headers,
            Authorization: `Bearer ${await this.uniqueAuthService.getToken()}`,
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
        // TODO: Test that this log provides enough info about which operation failed
        this.logger.error({
          msg: `Failed scope management request: ${normalizeError(error).message}`,
          err: error,
        });
        throw error;
      }
    });
  }
}
