import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DirectoriesSyncModule } from '../../directories-sync/directories-sync.module';
import { MailIngestionModule } from '../../mail-ingestion/mail-ingestion.module';
import { SubscriptionUtilsModule } from '../../user-utils/subscription-utils.module';
import { ExecuteFullSyncCommand } from './execute-full-sync.command';
import { FindInboxConfigByVersionQuery } from './find-inbox-config-by-version.query';
import { FullSyncListener } from './full-sync.listener';
import { GetFullSyncStatsQuery } from './get-full-sync-stats.query';
import { GetScopeIngestionStatsQuery } from './get-scope-ingestion-stats.query';
import { ProcessFullSyncBatchCommand } from './process-full-sync-batch.command';
import { RecoverFullSyncCommand } from './recover-full-sync.command';
import { StartFullSyncCommand } from './start-full-sync.command';
import { UpdateInboxConfigByVersionCommand } from './update-inbox-config-by-version.command';

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    SubscriptionUtilsModule,
    DirectoriesSyncModule,
    UniqueApiFeatureModule,
    MailIngestionModule,
  ],
  providers: [
    StartFullSyncCommand,
    ExecuteFullSyncCommand,
    RecoverFullSyncCommand,
    FullSyncListener,
    GetFullSyncStatsQuery,
    GetScopeIngestionStatsQuery,
    UpdateInboxConfigByVersionCommand,
    FindInboxConfigByVersionQuery,
    ProcessFullSyncBatchCommand,
  ],
  exports: [
    StartFullSyncCommand,
    GetFullSyncStatsQuery,
    GetScopeIngestionStatsQuery,
    UpdateInboxConfigByVersionCommand,
    FindInboxConfigByVersionQuery,
  ],
})
export class FullSyncModule {}
