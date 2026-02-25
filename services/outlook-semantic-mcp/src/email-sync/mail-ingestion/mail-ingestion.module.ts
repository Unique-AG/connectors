import { Module, Provider } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DirectoriesSyncModule } from '../directories-sync/directories-sync.module';
import { SubscriptionUtilsModule } from '../user-utils/subscription-utils.module';
import { FullSyncCommand } from './full-sync.command';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { IngestEmailCommand } from './ingest-email.command';
import { IngestEmailViaSubscriptionCommand } from './ingest-email-via-subscription.command';
import { RunFullSyncTool } from './tools/run-full-sync.tool';

const COMMANDS: Provider[] = [
  FullSyncCommand,
  IngestEmailViaSubscriptionCommand,
  IngestEmailCommand,
];

const QUERIES: Provider[] = [GetMessageDetailsQuery];

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    SubscriptionUtilsModule,
    DirectoriesSyncModule,
    UniqueApiFeatureModule,
  ],
  providers: [...COMMANDS, ...QUERIES, RunFullSyncTool],
  exports: [...COMMANDS, ...QUERIES],
})
export class MailIngestionModule {}
