import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { AuthModule } from '../auth/auth.module';
import { SharepointApiModule } from '../sharepoint-api/sharepoint-api.module';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { ContentFetchingStep } from './steps/content-fetching.step';
import { ContentRegistrationStep } from './steps/content-registration.step';
import { FileProcessingOrchestratorService } from './file-processing-orchestrator.service';
import { IngestionFinalizationStep } from './steps/ingestion-finalization.step';
import { ProcessingPipelineService } from './processing-pipeline.service';
import { StorageUploadStep } from './steps/storage-upload.step';
import { TokenValidationStep } from './steps/token-validation.step';

@Module({
  imports: [ConfigModule, SharepointApiModule, AuthModule, UniqueApiModule],
  providers: [
    ProcessingPipelineService,
    FileProcessingOrchestratorService,
    TokenValidationStep,
    ContentFetchingStep,
    ContentRegistrationStep,
    StorageUploadStep,
    IngestionFinalizationStep,
  ],
  exports: [ProcessingPipelineService, FileProcessingOrchestratorService],
})
export class ProcessingPipelineModule {}
