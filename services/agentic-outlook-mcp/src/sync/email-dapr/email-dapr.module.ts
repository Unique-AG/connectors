import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { LLMModule } from '../../llm/llm.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { QdrantModule } from '../../qdrant/qdrant.module';
import { EmailService } from './email.service';
import { EmailSyncService } from './email-sync.service';
import { LLMEmailCleanupService } from './lib/llm-email-cleanup/llm-email-cleanup.service';
import { LLMSummarizationService } from './lib/llm-summarization-service/llm-summarization.service';
import { EmbedActivity } from './workflows/embed.activity';
import { IndexActivity } from './workflows/index.activity';
import { ProcessActivity } from './workflows/process.activity';
import { UpdateStatusActivity } from './workflows/update-status.activity';
import { WorkflowRegistrationService } from './workflows/workflow-registration.service';

@Module({
  imports: [DrizzleModule, MsGraphModule, LLMModule, QdrantModule],
  providers: [
    EmailService,
    EmailSyncService,
    WorkflowRegistrationService,
    UpdateStatusActivity,
    EmbedActivity,
    IndexActivity,
    ProcessActivity,
    LLMEmailCleanupService,
    LLMSummarizationService,
  ],
  exports: [EmailService, EmailSyncService],
})
export class EmailDaprModule {}
