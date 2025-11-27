import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
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
      ) => {
        return new UniqueGraphqlClient(
          'scopeManagement',
          uniqueAuthService,
          configService,
          bottleneckFactory,
        );
      },
      inject: [UniqueAuthService, ConfigService, BottleneckFactory],
    },
    {
      provide: INGESTION_CLIENT,
      useFactory: (
        uniqueAuthService: UniqueAuthService,
        configService: ConfigService<Config, true>,
        bottleneckFactory: BottleneckFactory,
      ) => {
        return new UniqueGraphqlClient(
          'ingestion',
          uniqueAuthService,
          configService,
          bottleneckFactory,
        );
      },
      inject: [UniqueAuthService, ConfigService, BottleneckFactory],
    },
    {
      provide: IngestionHttpClient,
      useFactory: (
        uniqueAuthService: UniqueAuthService,
        configService: ConfigService<Config, true>,
        bottleneckFactory: BottleneckFactory,
      ) => {
        return new IngestionHttpClient(uniqueAuthService, configService, bottleneckFactory);
      },
      inject: [UniqueAuthService, ConfigService, BottleneckFactory],
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
