import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { AuthModule } from '../auth/auth.module';
import { MsGraphModule } from '../msgraph/msgraph.module';
import { ProcessingPipelineModule } from '../processing-pipeline/processing-pipeline.module';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { SharePointPathService } from '../utils/sharepoint-path.service';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';

@Module({
  imports: [ConfigModule, AuthModule, MsGraphModule, UniqueApiModule, ProcessingPipelineModule],
  providers: [SharepointSynchronizationService],
  exports: [SharepointSynchronizationService],
})
export class SharepointSynchronizationModule {}
