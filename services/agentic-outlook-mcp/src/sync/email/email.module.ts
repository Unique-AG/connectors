import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { AmqpModule } from '../amqp/amqp.module';
import { EmailService } from './email.service';
import { EmailSyncService } from './email-sync.service';
import { OrchestratorService } from './orchestrator.service';
import { IngestService } from './pipeline/ingest.service';
import { ProcessService } from './pipeline/process.service';
import { PipelineRetryService } from './pipeline-retry.service';

@Module({
  imports: [MsGraphModule, DrizzleModule, AmqpModule],
  providers: [
    EmailService,
    EmailSyncService,
    OrchestratorService,
    PipelineRetryService,
    IngestService,
    ProcessService,
  ],
  exports: [EmailService, EmailSyncService],
})
export class EmailModule {}
