import { Module } from '@nestjs/common';
import { AMQPModule } from '~/amqp/amqp.module';
import { DrizzleModule } from '~/db/drizzle.module';
import { FullSyncRecoveryService } from './full-sync-recovery.service';
import { LiveCatchUpCronService } from './live-catch-up/live-catch-up-cron.service';
import { StuckSyncRecoveryService } from './stuck-sync-recovery.service';
import { SyncOnFilterChangeService } from './sync-on-filter-change.service';

@Module({
  imports: [DrizzleModule, AMQPModule],
  providers: [StuckSyncRecoveryService, SyncOnFilterChangeService, LiveCatchUpCronService, FullSyncRecoveryService],
  exports: [StuckSyncRecoveryService, SyncOnFilterChangeService, LiveCatchUpCronService, FullSyncRecoveryService],
})
export class StuckSyncRecoveryModule {}
