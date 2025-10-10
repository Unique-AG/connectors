import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { AmqpModule } from '../amqp/amqp.module';
import { EmailService } from './email.service';
import { EmailSyncService } from './email-sync.service';
import { IngestService } from './pipeline/ingest.service';

@Module({
  imports: [MsGraphModule, DrizzleModule, AmqpModule],
  providers: [EmailService, EmailSyncService, IngestService],
  exports: [EmailService, EmailSyncService],
})
export class EmailModule {}
