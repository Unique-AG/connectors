import { Module } from '@nestjs/common';
import { AMQPModule } from '~/amqp/amqp.module';
import { DrizzleModule } from '~/db/drizzle.module';
import { LiveCatchUpCronService } from './live-catch-up/live-catch-up-cron.service';
import { StuckSyncRecoveryService } from './stuck-sync-recovery.service';
import { SyncOnFilterChangeService } from './sync-on-filter-change.service';

@Module({
  imports: [DrizzleModule, AMQPModule],
  providers: [StuckSyncRecoveryService, SyncOnFilterChangeService, LiveCatchUpCronService],
  exports: [StuckSyncRecoveryService, SyncOnFilterChangeService, LiveCatchUpCronService],
})
export class StuckSyncRecoveryModule {}
