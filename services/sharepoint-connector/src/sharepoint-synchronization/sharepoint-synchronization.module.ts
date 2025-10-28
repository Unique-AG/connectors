import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { MicrosoftApisModule } from '../microsoft-apis/microsoft-apis.module';
import { ProcessingPipelineModule } from '../processing-pipeline/processing-pipeline.module';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';

@Module({
  imports: [ConfigModule, MicrosoftApisModule, UniqueApiModule, ProcessingPipelineModule],
  providers: [SharepointSynchronizationService],
  exports: [SharepointSynchronizationService],
})
export class SharepointSynchronizationModule {}
