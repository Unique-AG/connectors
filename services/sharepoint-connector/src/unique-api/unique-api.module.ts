import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { MetricService } from 'nestjs-otel';
import { Config } from '../config';
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
        metricService: MetricService,
      ) => {
        return new UniqueGraphqlClient(
          'scopeManagement',
          uniqueAuthService,
          configService,
          metricService,
        );
      },
      inject: [UniqueAuthService, ConfigService, MetricService],
    },
    {
      provide: INGESTION_CLIENT,
      useFactory: (
        uniqueAuthService: UniqueAuthService,
        configService: ConfigService<Config, true>,
        metricService: MetricService,
      ) => {
        return new UniqueGraphqlClient(
          'ingestion',
          uniqueAuthService,
          configService,
          metricService,
        );
      },
      inject: [UniqueAuthService, ConfigService, MetricService],
    },
    IngestionHttpClient,
    UniqueFileIngestionService,
    UniqueFilesService,
    UniqueScopesService,
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
