import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { MicrosoftApisModule } from '../microsoft-apis/microsoft-apis.module';
import { FetchGraphPermissionsMapQuery } from '../permissions-sync/fetch-graph-permissions-map.query';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import { ProcessingPipelineModule } from '../processing-pipeline/processing-pipeline.module';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { ContentSyncService } from './content-sync.service';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';

@Module({
  imports: [ConfigModule, MicrosoftApisModule, UniqueApiModule, ProcessingPipelineModule],
  providers: [
    SharepointSynchronizationService,
    ContentSyncService,
    PermissionsSyncService,
    FetchGraphPermissionsMapQuery,
  ],
  exports: [SharepointSynchronizationService],
})
export class SharepointSynchronizationModule {}
