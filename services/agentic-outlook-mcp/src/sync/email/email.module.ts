import { TemporalModule } from '@unique-ag/temporal';
import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { LLMModule } from '../../llm/llm.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { QdrantModule } from '../../qdrant/qdrant.module';
import { CleanupActivity } from './activities/cleanup.activity';
import { CreateChunksActivity } from './activities/create-chunks.activity';
import { EmbedDenseActivity } from './activities/embed-dense.activity';
import { IndexActivity } from './activities/index.activity';
import { LoadEmailActivity } from './activities/load-email.activity';
import { SaveEmailResultsActivity } from './activities/save-email-results.activity';
import { SavePointsActivity } from './activities/save-points.activity';
import { SummarizeBodyActivity } from './activities/summarize-body.activity';
import { SummarizeThreadActivity } from './activities/summarize-thread.activity';
import { TranslateActivity } from './activities/translate.activity';
import { UpdateStatusActivity } from './activities/update-status.activity';
import { EmailService } from './email.service';
import { EmailDebugController } from './email-debug.controller';
import { EmailSyncService } from './email-sync.service';
import { IngestService } from './ingest.service';
import { LLMEmailCleanupService } from './lib/llm-email-cleanup/llm-email-cleanup.service';
import { LLMSummarizationService } from './lib/llm-summarization-service/llm-summarization.service';
import { LLMTranslationService } from './lib/llm-translation-service/llm-translation.service';

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
    CleanupActivity,
    CreateChunksActivity,
    EmbedDenseActivity,
    IndexActivity,
    IngestService,
    LLMEmailCleanupService,
    LLMSummarizationService,
    LLMTranslationService,
    LoadEmailActivity,
    SaveEmailResultsActivity,
    SavePointsActivity,
    SummarizeBodyActivity,
    SummarizeThreadActivity,
    TranslateActivity,
    UpdateStatusActivity,
  ],
  exports: [EmailService, EmailSyncService],
})
export class EmailModule {}
