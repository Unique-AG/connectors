import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DirectoriesSyncModule } from '../directories-sync/directories-sync.module';
import { SubscriptionUtilsModule } from '../user-utils/subscription-utils.module';
import { FullSyncCommand } from './full-sync.command';
import { GetFullSyncStatsQuery } from './get-full-sync-stats.query';

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    SubscriptionUtilsModule,
    DirectoriesSyncModule,
    UniqueApiFeatureModule,
  ],
  providers: [FullSyncCommand, GetFullSyncStatsQuery],
  exports: [FullSyncCommand, GetFullSyncStatsQuery],
})
export class FullSyncModule {}
