import { Module } from '@nestjs/common';
import { AMQPModule } from '~/amqp/amqp.module';
import { DrizzleModule } from '~/db/drizzle.module';
import { FullSyncSchedulerService } from './full-sync-scheduler.service';
import { LiveCatchUpCronService } from './live-catch-up/live-catch-up-cron.service';
import { LiveCatchupRecoveryService } from './live-catchup-recovery.service';
import { SyncOnFilterChangeService } from './sync-on-filter-change.service';

@Module({
  imports: [DrizzleModule, AMQPModule],
  providers: [
    LiveCatchupRecoveryService,
    SyncOnFilterChangeService,
    LiveCatchUpCronService,
    FullSyncSchedulerService,
  ],
  exports: [
    LiveCatchupRecoveryService,
    SyncOnFilterChangeService,
    LiveCatchUpCronService,
    FullSyncSchedulerService,
  ],
})
export class SyncRecoveryModule {}
