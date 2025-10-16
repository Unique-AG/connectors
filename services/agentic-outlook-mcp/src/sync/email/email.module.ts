import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { LLMModule } from '../../llm/llm.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { AmqpModule } from '../amqp/amqp.module';
import { EmailService } from './email.service';
import { EmailSyncService } from './email-sync.service';
import { LLMEmailCleanupService } from './lib/llm-email-cleanup/llm-email-cleanup.service';
import { OrchestratorService } from './orchestrator.service';
import { IngestService } from './pipeline/ingest.service';
import { ProcessService } from './pipeline/process.service';
import { PipelineRetryService } from './pipeline-retry.service';
import { TracePropagationService } from './trace-propagation.service';

@Module({
  imports: [MsGraphModule, DrizzleModule, AmqpModule, LLMModule],
  providers: [
    EmailService,
    EmailSyncService,
    OrchestratorService,
    PipelineRetryService,
    TracePropagationService,
    IngestService,
    ProcessService,
    LLMEmailCleanupService,
  ],
  exports: [EmailService, EmailSyncService],
})
export class EmailModule {}
