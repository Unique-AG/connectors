import { Inject, Injectable } from '@nestjs/common';
import { constant, fullJitter, upto } from '@proventuslabs/retry-strategies';
import {
  pipeline,
  withAuthorization,
  withBaseUrl,
  withHeaders,
  withResponseError,
  withRetryAfter,
  withRetryStatus,
} from '@qfetch/qfetch';
import { GraphError } from './graph-error';
import { MODULE_OPTIONS_TOKEN, OPTIONS_TYPE } from './graph-sdk.module.options';
import { GraphUserClient } from './graph-user-client';

@Injectable()
export class GraphClientService {
  public constructor(@Inject(MODULE_OPTIONS_TOKEN) private readonly options: typeof OPTIONS_TYPE) {}

  public forUser(userProfileId: string): GraphUserClient {
    const baseUrl = `https://graph.microsoft.com/${this.options.apiVersion}`;
    const { maxAttempts, maxServerDelay } = this.options.retry;

    const fetchFn = pipeline(
      withBaseUrl(baseUrl),

      withHeaders({
        'Content-Type': 'application/json',
        ...this.options.defaultHeaders,
      }),

      withAuthorization({
        tokenProvider: {
          getToken: async () => ({
            accessToken: await this.options.getToken(userProfileId),
            tokenType: 'Bearer',
          }),
        },
        strategy: () => upto(1, constant(0)),
      }),

      withRetryAfter({
        strategy: () => upto(maxAttempts, fullJitter(100, 5_000)),
        maxServerDelay,
      }),

      withRetryStatus({
        strategy: () => upto(maxAttempts, fullJitter(200, 10_000)),
        retryableStatuses: new Set([500, 502, 503, 504]),
      }),

      withResponseError({
        defaultMapper: async (response: Response) => {
          const body: unknown = await response.json().catch(() => ({}));
          return GraphError.fromResponse(response.status, body, response.headers);
        },
      }),
    )(fetch);

    return new GraphUserClient(fetchFn);
  }
}
