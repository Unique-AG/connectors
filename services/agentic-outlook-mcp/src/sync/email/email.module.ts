import { TemporalModule } from '@unique-ag/temporal';
import { Module } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { OpenTelemetryWorkflowClientInterceptor } from '@temporalio/interceptors-opentelemetry';
import { AppConfig, AppSettings } from '../../app-settings';
import { DenseEmbeddingModule } from '../../dense-embedding/dense-embedding.module';
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
import { EmailSyncService } from './email-sync.service';
import { IngestService } from './ingest.service';

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    LLMModule,
    DenseEmbeddingModule,
    QdrantModule,
    TemporalModule.registerWorkerAsync({
      useFactory: (configService: ConfigService<AppConfig, true>) => ({
        runtimeOptions: {
          telemetryOptions: {
            metrics: {
              otel: {
                url: configService.get(AppSettings.OTEL_EXPORTER_OTLP_ENDPOINT),
                metricsExportInterval: '1s',
              },
            },
          },
        },
        workerOptions: {
          taskQueue: 'default',
          workflowsPath: require.resolve('./temporal/ingest.workflow'),
        },
      }),
      inject: [ConfigService],
    }),
    TemporalModule.registerClient({
      workflowOptions: {
        interceptors: [new OpenTelemetryWorkflowClientInterceptor()],
      },
    }),
  ],
  providers: [
    EmailService,
    EmailSyncService,
    CleanupActivity,
    CreateChunksActivity,
    EmbedDenseActivity,
    IndexActivity,
    IngestService,
    LoadEmailActivity,
    SaveEmailResultsActivity,
    SavePointsActivity,
    SummarizeBodyActivity,
    SummarizeThreadActivity,
    TranslateActivity,
    UpdateStatusActivity,
  ],
  exports: [EmailService, EmailSyncService, IngestService],
})
export class EmailModule {}
