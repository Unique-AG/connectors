import { Module } from '@nestjs/common';
import { AMQPModule } from '~/amqp/amqp.module';
import { DrizzleModule } from '~/db/drizzle.module';
import { FullSyncSchedulerService } from './full-sync-scheduler.service';
import { LiveCatchupRecoveryService } from './live-catchup-recovery.service';
import { SyncOnFilterChangeService } from './sync-on-filter-change.service';

@Module({
  imports: [DrizzleModule, AMQPModule],
  providers: [LiveCatchupRecoveryService, SyncOnFilterChangeService, FullSyncSchedulerService],
  exports: [LiveCatchupRecoveryService, SyncOnFilterChangeService, FullSyncSchedulerService],
})
export class SyncRecoveryModule {}
