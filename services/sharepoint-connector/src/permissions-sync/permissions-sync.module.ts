import { Module } from '@nestjs/common';
import { MicrosoftApisModule } from '../microsoft-apis/microsoft-apis.module';
import { FetchGraphPermissionsMapQuery } from '../permissions-sync/fetch-graph-permissions-map.query';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { FetchGroupsWithMembershipsQuery } from './fetch-groups-with-memberships.query';
import { PermissionsSyncService } from './permissions-sync.service';

@Module({
  imports: [MicrosoftApisModule, UniqueApiModule],
  providers: [
    PermissionsSyncService,
    FetchGraphPermissionsMapQuery,
    FetchGroupsWithMembershipsQuery,
  ],
  exports: [PermissionsSyncService],
})
export class PermissionsSyncModule {}
