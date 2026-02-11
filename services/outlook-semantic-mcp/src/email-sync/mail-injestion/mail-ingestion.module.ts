import { Module, Provider } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueModule } from '~/unique/unique.module';
import { FullSyncCommand } from './full-sync.command';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { IngestEmailCommand } from './ingest-email.command';
import { IngestEmailViaSubscriptionCommand } from './ingest-email-via-subscription.command';
import { IngestionListener } from './ingestion.listener';
import { UpdateMetadataCommand } from './update-metadata.command';

const COMMANDS: Provider[] = [
  FullSyncCommand,
  IngestEmailViaSubscriptionCommand,
  IngestEmailCommand,
  IngestionListener,
  UpdateMetadataCommand,
];

const QUERIES: Provider[] = [GetMessageDetailsQuery];

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueModule],
  providers: [...COMMANDS, ...QUERIES],
  exports: [...COMMANDS, ...QUERIES],
})
export class MailIngestionModule {}
