import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { MetricsModule } from '../metrics/metrics.module';
import { MicrosoftApisModule } from '../microsoft-apis/microsoft-apis.module';
import { HttpClientService } from '../shared/services/http-client.service';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { ItemProcessingOrchestratorService } from './item-processing-orchestrator.service';
import { ProcessingPipelineService } from './processing-pipeline.service';
import { AspxProcessingStep } from './steps/aspx-processing.step';
import { ContentRegistrationStep } from './steps/content-registration.step';
import { IngestionFinalizationStep } from './steps/ingestion-finalization.step';
import { UploadContentStep } from './steps/upload-content.step';

@Module({
  imports: [ConfigModule, MetricsModule, MicrosoftApisModule, UniqueApiModule],
  providers: [
    ProcessingPipelineService,
    ItemProcessingOrchestratorService,
    AspxProcessingStep,
    ContentRegistrationStep,
    UploadContentStep,
    IngestionFinalizationStep,
    HttpClientService,
  ],
  exports: [ProcessingPipelineService, ItemProcessingOrchestratorService],
})
export class ProcessingPipelineModule {}
