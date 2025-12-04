import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { type Counter, type Histogram } from '@opentelemetry/api';
import { Config } from '../config';
import {
  SPC_UNIQUE_GRAPHQL_API_REQUEST_DURATION_SECONDS,
  SPC_UNIQUE_GRAPHQL_API_SLOW_REQUESTS_TOTAL,
} from '../metrics';
import { MetricsModule } from '../metrics/metrics.module';
import { HttpClientService } from '../shared/services/http-client.service';
import { BottleneckFactory } from '../utils/bottleneck.factory';
import { IngestionHttpClient } from './clients/ingestion-http.client';
import {
  INGESTION_CLIENT,
  SCOPE_MANAGEMENT_CLIENT,
  UniqueGraphqlClient,
} from './clients/unique-graphql.client';
import { UniqueAuthService } from './unique-auth.service';
import { UniqueFileIngestionService } from './unique-file-ingestion/unique-file-ingestion.service';
import { UniqueFilesService } from './unique-files/unique-files.service';
import { UniqueGroupsService } from './unique-groups/unique-groups.service';
import { UniqueScopesService } from './unique-scopes/unique-scopes.service';
import { UniqueUsersService } from './unique-users/unique-users.service';

@Module({
  imports: [ConfigModule, MetricsModule],
  providers: [
    UniqueAuthService,
    UniqueGroupsService,
    UniqueUsersService,
    UniqueFileIngestionService,
    UniqueFilesService,
    UniqueScopesService,
    BottleneckFactory,
    HttpClientService,
    IngestionHttpClient,
    {
      provide: SCOPE_MANAGEMENT_CLIENT,
      useFactory: (
        uniqueAuthService: UniqueAuthService,
        configService: ConfigService<Config, true>,
        bottleneckFactory: BottleneckFactory,
        spcUniqueGraphqlApiRequestDurationSeconds: Histogram,
        spcUniqueGraphqlApiSlowRequestsTotal: Counter,
      ) => {
        return new UniqueGraphqlClient(
          'scopeManagement',
          uniqueAuthService,
          configService,
          bottleneckFactory,
          spcUniqueGraphqlApiRequestDurationSeconds,
          spcUniqueGraphqlApiSlowRequestsTotal,
        );
      },
      inject: [
        UniqueAuthService,
        ConfigService,
        BottleneckFactory,
        SPC_UNIQUE_GRAPHQL_API_REQUEST_DURATION_SECONDS,
        SPC_UNIQUE_GRAPHQL_API_SLOW_REQUESTS_TOTAL,
      ],
    },
    {
      provide: INGESTION_CLIENT,
      useFactory: (
        uniqueAuthService: UniqueAuthService,
        configService: ConfigService<Config, true>,
        bottleneckFactory: BottleneckFactory,
        spcUniqueGraphqlApiRequestDurationSeconds: Histogram,
        spcUniqueGraphqlApiSlowRequestsTotal: Counter,
      ) => {
        return new UniqueGraphqlClient(
          'ingestion',
          uniqueAuthService,
          configService,
          bottleneckFactory,
          spcUniqueGraphqlApiRequestDurationSeconds,
          spcUniqueGraphqlApiSlowRequestsTotal,
        );
      },
      inject: [
        UniqueAuthService,
        ConfigService,
        BottleneckFactory,
        SPC_UNIQUE_GRAPHQL_API_REQUEST_DURATION_SECONDS,
        SPC_UNIQUE_GRAPHQL_API_SLOW_REQUESTS_TOTAL,
      ],
    },
  ],
  exports: [
    UniqueAuthService,
    UniqueGroupsService,
    UniqueScopesService,
    UniqueUsersService,
    UniqueFileIngestionService,
    UniqueFilesService,
    INGESTION_CLIENT,
    SCOPE_MANAGEMENT_CLIENT,
  ],
})
export class UniqueApiModule {}
