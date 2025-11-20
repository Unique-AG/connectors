import { TemporalModule } from '@unique-ag/temporal';
import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { LLMModule } from '../../llm/llm.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { QdrantModule } from '../../qdrant/qdrant.module';
import { EmbedActivity } from './activities/embed.activity';
import { IndexActivity } from './activities/index.activity';
import { ProcessActivity } from './activities/process.activity';
import { UpdateStatusActivity } from './activities/update-status.activity';
import { EmailService } from './email.service';
import { EmailDebugController } from './email-debug.controller';
import { EmailSyncService } from './email-sync.service';
import { IngestService } from './ingest.service';
import { LLMEmailCleanupService } from './lib/llm-email-cleanup/llm-email-cleanup.service';
import { LLMSummarizationService } from './lib/llm-summarization-service/llm-summarization.service';

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    LLMModule,
    QdrantModule,
    TemporalModule.registerWorker({
      workerOptions: {
        taskQueue: 'default',
        workflowsPath: require.resolve('./temporal/ingest.workflow'),
      },
    }),

    TemporalModule.registerClient(),
  ],
  controllers: [EmailDebugController],
  providers: [
    EmailService,
    EmailSyncService,
    EmbedActivity,
    IndexActivity,
    IngestService,
    LLMEmailCleanupService,
    LLMSummarizationService,
    ProcessActivity,
    UpdateStatusActivity,
  ],
  exports: [EmailService, EmailSyncService],
})
export class EmailModule {}
