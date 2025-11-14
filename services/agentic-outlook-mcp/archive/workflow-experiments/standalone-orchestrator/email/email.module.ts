import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { LLMModule } from '../../llm/llm.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { QdrantModule } from '../../qdrant/qdrant.module';
import { AmqpModule } from '../amqp/amqp.module';
import { AmqpOrchestratorService } from './amqp-orchestrator.service';
import { EmailService } from './email.service';
import { EmailSyncService } from './email-sync.service';
import { LLMEmailCleanupService } from './lib/llm-email-cleanup/llm-email-cleanup.service';
import { LLMSummarizationService } from './lib/llm-summarization-service/llm-summarization.service';
import { EmbedService } from './pipeline/embed.service';
import { IndexService } from './pipeline/index.service';
import { IngestService } from './pipeline/ingest.service';
import { ProcessService } from './pipeline/process.service';
import { RetryService } from './retry.service';
import { TracePropagationService } from './trace-propagation.service';

@Module({
  imports: [MsGraphModule, DrizzleModule, AmqpModule, LLMModule, QdrantModule],
  providers: [
    EmailService,
    EmailSyncService,
    AmqpOrchestratorService,
    RetryService,
    TracePropagationService,
    IngestService,
    ProcessService,
    EmbedService,
    IndexService,
    LLMEmailCleanupService,
    LLMSummarizationService,
  ],
  exports: [EmailService, EmailSyncService, AmqpOrchestratorService],
})
export class EmailModule {}
