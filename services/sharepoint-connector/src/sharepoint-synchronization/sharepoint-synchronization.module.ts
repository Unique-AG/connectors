import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { MicrosoftApisModule } from '../microsoft-apis/microsoft-apis.module';
import { ProcessingPipelineModule } from '../processing-pipeline/processing-pipeline.module';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { ContentSyncService } from './content-sync.service';
import { PermissionsSyncService } from './permissions-sync.service';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';

@Module({
  imports: [ConfigModule, MicrosoftApisModule, UniqueApiModule, ProcessingPipelineModule],
  providers: [SharepointSynchronizationService, ContentSyncService, PermissionsSyncService],
  exports: [SharepointSynchronizationService],
})
export class SharepointSynchronizationModule {}
