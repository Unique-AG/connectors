import { Module } from '@nestjs/common';
import { MicrosoftApisModule } from '../microsoft-apis/microsoft-apis.module';
import { FetchGraphPermissionsMapQuery } from '../permissions-sync/fetch-graph-permissions-map.query';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { FetchGroupsWithMembershipsQuery } from './fetch-groups-with-memberships.query';
import { PermissionsSyncService } from './permissions-sync.service';
import { SyncSharepointFilesPermissionsToUniqueCommand } from './sync-sharepoint-files-permissions-to-unique.command';
import { SyncSharepointFolderPermissionsToUniqueCommand } from './sync-sharepoint-folder-permissions-to-unique.command';
import { SyncSharepointGroupsToUniqueCommand } from './sync-sharepoint-groups-to-unique.command';

@Module({
  imports: [MicrosoftApisModule, UniqueApiModule],
  providers: [
    PermissionsSyncService,
    FetchGraphPermissionsMapQuery,
    FetchGroupsWithMembershipsQuery,
    SyncSharepointGroupsToUniqueCommand,
    SyncSharepointFilesPermissionsToUniqueCommand,
    SyncSharepointFolderPermissionsToUniqueCommand,
  ],
  exports: [PermissionsSyncService],
})
export class PermissionsSyncModule {}
