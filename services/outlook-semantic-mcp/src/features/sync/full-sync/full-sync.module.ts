import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DirectoriesSyncModule } from '../../directories-sync/directories-sync.module';
import { SubscriptionUtilsModule } from '../../user-utils/subscription-utils.module';
import { ExecuteFullSyncCommand } from './execute-full-sync.command';
import { FullSyncListener } from './full-sync.listener';
import { GetFullSyncStatsQuery } from './get-full-sync-stats.query';
import { RecoverFullSyncCommand } from './recover-full-sync.command';
import { StartFullSyncCommand } from './start-full-sync.command';

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    SubscriptionUtilsModule,
    DirectoriesSyncModule,
    UniqueApiFeatureModule,
  ],
  providers: [
    StartFullSyncCommand,
    ExecuteFullSyncCommand,
    RecoverFullSyncCommand,
    FullSyncListener,
    GetFullSyncStatsQuery,
  ],
  exports: [StartFullSyncCommand, GetFullSyncStatsQuery],
})
export class FullSyncModule {}
