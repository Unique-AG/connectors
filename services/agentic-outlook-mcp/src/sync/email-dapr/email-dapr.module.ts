import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { LLMModule } from '../../llm/llm.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { QdrantModule } from '../../qdrant/qdrant.module';
import { EmailService } from './email.service';
import { EmailSyncService } from './email-sync.service';

@Module({
  imports: [DrizzleModule, MsGraphModule, LLMModule, QdrantModule],
  providers: [EmailService, EmailSyncService],
  exports: [EmailService, EmailSyncService],
})
export class EmailDaprModule {}
