import { Module } from '@nestjs/common';
import { ScheduleModule } from '@nestjs/schedule';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DirectoriesSyncModule } from '../directories-sync/directories-sync.module';
import { SubscriptionUtilsModule } from '../user-utils/subscription-utils.module';
import { FullSyncCommand } from './full-sync.command';
import { GetFullSyncStatsQuery } from './get-full-sync-stats.query';
import { StuckSyncRecoveryService } from './stuck-sync-recovery.service';
import { SyncOnFilterChangeService } from './sync-on-filter-change.service';

@Module({
  imports: [
    ScheduleModule.forRoot(),
    DrizzleModule,
    MsGraphModule,
    SubscriptionUtilsModule,
    DirectoriesSyncModule,
    UniqueApiFeatureModule,
  ],
  providers: [
    FullSyncCommand,
    GetFullSyncStatsQuery,
    SyncOnFilterChangeService,
    StuckSyncRecoveryService,
  ],
  exports: [
    FullSyncCommand,
    GetFullSyncStatsQuery,
    SyncOnFilterChangeService,
    StuckSyncRecoveryService,
  ],
})
export class FullSyncModule {}
