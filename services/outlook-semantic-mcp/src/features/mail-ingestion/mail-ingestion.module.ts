import { Module, Provider } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DirectoriesSyncModule } from '../directories-sync/directories-sync.module';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { IngestEmailCommand } from './ingest-email.command';
import { IngestEmailFromFullSyncCommand } from './ingest-email-from-full-sync.command';
import { IngestEmailViaSubscriptionCommand } from './ingest-email-via-subscription.command';

const PRIVATE_COMMANDS: Provider[] = [IngestEmailCommand];

const COMMANDS: Provider[] = [IngestEmailViaSubscriptionCommand, IngestEmailFromFullSyncCommand];

const QUERIES: Provider[] = [GetMessageDetailsQuery];

@Module({
  imports: [
    ConfigModule,
    DrizzleModule,
    MsGraphModule,
    DirectoriesSyncModule,
    UniqueApiFeatureModule,
  ],
  providers: [...PRIVATE_COMMANDS, ...COMMANDS, ...QUERIES],
  exports: [...COMMANDS, ...QUERIES],
})
export class MailIngestionModule {}
