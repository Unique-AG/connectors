import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { MicrosoftApisModule } from '../microsoft-apis/microsoft-apis.module';
import { ScopeManagementService } from '../sharepoint-synchronization/scope-management.service';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { ItemProcessingOrchestratorService } from './item-processing-orchestrator.service';
import { ProcessingPipelineService } from './processing-pipeline.service';
import { AspxProcessingStep } from './steps/aspx-processing.step';
import { ContentFetchingStep } from './steps/content-fetching.step';
import { ContentRegistrationStep } from './steps/content-registration.step';
import { IngestionFinalizationStep } from './steps/ingestion-finalization.step';
import { StorageUploadStep } from './steps/storage-upload.step';

@Module({
  imports: [ConfigModule, MicrosoftApisModule, UniqueApiModule],
  providers: [
    ProcessingPipelineService,
    ItemProcessingOrchestratorService,
    ScopeManagementService,
    ContentFetchingStep,
    AspxProcessingStep,
    ContentRegistrationStep,
    StorageUploadStep,
    IngestionFinalizationStep,
  ],
  exports: [ProcessingPipelineService, ItemProcessingOrchestratorService],
})
export class ProcessingPipelineModule {}
