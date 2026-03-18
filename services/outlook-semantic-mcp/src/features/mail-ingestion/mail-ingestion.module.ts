import { Module, Provider } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DirectoriesSyncModule } from '../directories-sync/directories-sync.module';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { IngestEmailCommand } from './ingest-email.command';
import { IngestFullSyncMessageCommand } from './ingest-full-sync-message.command';
import { IngestEmailLiveCatchupMessageCommand } from './ingest-live-catchup-message.command';

const COMMANDS: Provider[] = [
  IngestEmailCommand,
  IngestFullSyncMessageCommand,
  IngestEmailLiveCatchupMessageCommand,
];

const QUERIES: Provider[] = [GetMessageDetailsQuery];

@Module({
  imports: [
    ConfigModule,
    DrizzleModule,
    MsGraphModule,
    DirectoriesSyncModule,
    UniqueApiFeatureModule,
  ],
  providers: [...COMMANDS, ...QUERIES],
  exports: [...COMMANDS, ...QUERIES],
})
export class MailIngestionModule {}
