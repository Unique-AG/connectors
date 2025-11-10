import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { HttpClientModule } from '../http-client.module';
import { IngestionClient } from './clients/ingestion.client';
import { ScopeManagementClient } from './clients/scope-management.client';
import { UniqueApiService } from './unique-api.service';
import { UniqueAuthService } from './unique-auth.service';
import { UniqueGroupsService } from './unique-groups/unique-groups.service';
import { UniqueUsersService } from './unique-users/unique-users.service';

@Module({
  imports: [ConfigModule, HttpClientModule],
  providers: [
    UniqueApiService,
    UniqueAuthService,
    UniqueGroupsService,
    UniqueUsersService,
    ScopeManagementClient,
    IngestionClient,
  ],
  exports: [UniqueApiService, UniqueAuthService, UniqueGroupsService, UniqueUsersService],
})
export class UniqueApiModule {}
