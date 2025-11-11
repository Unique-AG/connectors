import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { IngestionClient } from './clients/ingestion.client';
import { IngestionHttpClient } from './clients/ingestion-http.client';
import { ScopeManagementClient } from './clients/scope-management.client';
import { UniqueAuthService } from './unique-auth.service';
import { UniqueFileIngestionService } from './unique-file-ingestion/unique-file-ingestion.service';
import { UniqueGroupsService } from './unique-groups/unique-groups.service';
import { UniqueUsersService } from './unique-users/unique-users.service';

@Module({
  imports: [ConfigModule],
  providers: [
    UniqueAuthService,
    UniqueGroupsService,
    UniqueUsersService,
    ScopeManagementClient,
    IngestionClient,
    IngestionHttpClient,
    UniqueFileIngestionService,
  ],
  exports: [UniqueAuthService, UniqueGroupsService, UniqueUsersService, UniqueFileIngestionService],
})
export class UniqueApiModule {}
