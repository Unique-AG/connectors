import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { MsGraphModule } from '../msgraph/msgraph.module';
import { ProcessingPipelineModule } from '../processing-pipeline/processing-pipeline.module';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { ContentSyncService } from './content-sync.service';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';

@Module({
  imports: [ConfigModule, MsGraphModule, UniqueApiModule, ProcessingPipelineModule],
  providers: [SharepointSynchronizationService, ContentSyncService],
  exports: [SharepointSynchronizationService],
})
export class SharepointSynchronizationModule {}
