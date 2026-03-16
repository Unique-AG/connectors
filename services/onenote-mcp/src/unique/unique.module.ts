import { Logger, Module } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { fullJitter, upto } from '@proventuslabs/retry-strategies';
import {
  type FetchFn,
  pipeline,
  withBaseUrl,
  withHeaders,
  withResponseError,
  withRetryStatus,
} from '@qfetch/qfetch';
import type { UniqueConfigNamespaced } from '~/config';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { UNIQUE_FETCH, UNIQUE_REQUEST_HEADERS } from './unique.consts';
import { UniqueContentService } from './unique-content.service';
import { UniqueScopeService } from './unique-scope.service';
import { UniqueUserService } from './unique-user.service';

function redactHeaderValue(key: string, value: string): string {
  if (key === 'authorization' && value.length > 20) {
    return `${value.slice(0, 15)}...${value.slice(-4)}`;
  }
  return value;
}

@Module({
  imports: [DrizzleModule],
  providers: [
    {
      provide: UNIQUE_REQUEST_HEADERS,
      inject: [ConfigService],
      useFactory(config: ConfigService<UniqueConfigNamespaced, true>): Record<string, string> {
        const uniqueConfig = config.get('unique', { infer: true });
        const { authorization: _, ...extraHeaders } = uniqueConfig.serviceExtraHeaders;
        return {
          'x-api-version': uniqueConfig.apiVersion,
          ...extraHeaders,
        };
      },
    },
    {
      provide: UNIQUE_FETCH,
      inject: [ConfigService],
      useFactory(config: ConfigService<UniqueConfigNamespaced, true>): FetchFn {
        const logger = new Logger('UniqueModule');
        const uniqueConfig = config.get('unique', { infer: true });

        const { authorization: _, ...extraHeaders } = uniqueConfig.serviceExtraHeaders;
        const headers: Record<string, string> = {
          'x-api-version': uniqueConfig.apiVersion,
          ...extraHeaders,
        };

        const redactedHeaders = Object.fromEntries(
          Object.entries(headers).map(([k, v]) => [k, redactHeaderValue(k, v)]),
        );

        logger.log(
          {
            apiBaseUrl: uniqueConfig.apiBaseUrl,
            headerKeys: Object.keys(headers),
            headers: redactedHeaders,
          },
          'Unique API fetch client configured',
        );

        return pipeline(
          withBaseUrl(uniqueConfig.apiBaseUrl),
          withHeaders(headers),
          withResponseError(),
          withRetryStatus({
            strategy: () => upto(5, fullJitter(1_000, 30_000)),
            retryableStatuses: new Set([429, 502, 503, 504]),
          }),
        )(fetch);
      },
    },
    UniqueUserService,
    UniqueScopeService,
    UniqueContentService,
  ],
  exports: [
    UNIQUE_FETCH,
    UNIQUE_REQUEST_HEADERS,
    UniqueContentService,
    UniqueUserService,
    UniqueScopeService,
  ],
})
export class UniqueModule {}
