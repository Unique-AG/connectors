import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { MetricService } from 'nestjs-otel';
import { Config } from '../config';
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
  imports: [ConfigModule],
  providers: [
    UniqueAuthService,
    UniqueGroupsService,
    UniqueUsersService,
    {
      provide: SCOPE_MANAGEMENT_CLIENT,
      useFactory: (
        uniqueAuthService: UniqueAuthService,
        configService: ConfigService<Config, true>,
        bottleneckFactory: BottleneckFactory,
        metricService: MetricService,
      ) => {
        return new UniqueGraphqlClient(
          'scopeManagement',
          uniqueAuthService,
          configService,
          bottleneckFactory,
          metricService,
        );
      },
      inject: [UniqueAuthService, ConfigService, BottleneckFactory, MetricService],
    },
    {
      provide: INGESTION_CLIENT,
      useFactory: (
        uniqueAuthService: UniqueAuthService,
        configService: ConfigService<Config, true>,
        bottleneckFactory: BottleneckFactory,
        metricService: MetricService,
      ) => {
        return new UniqueGraphqlClient(
          'ingestion',
          uniqueAuthService,
          configService,
          bottleneckFactory,
          metricService,
        );
      },
      inject: [UniqueAuthService, ConfigService, BottleneckFactory, MetricService],
    },
    {
      provide: IngestionHttpClient,
      useFactory: (
        uniqueAuthService: UniqueAuthService,
        configService: ConfigService<Config, true>,
        bottleneckFactory: BottleneckFactory,
        metricService: MetricService,
      ) => {
        return new IngestionHttpClient(
          uniqueAuthService,
          configService,
          bottleneckFactory,
          metricService,
        );
      },
      inject: [UniqueAuthService, ConfigService, BottleneckFactory, MetricService],
    },
    UniqueFileIngestionService,
    UniqueFilesService,
    UniqueScopesService,
    BottleneckFactory,
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
