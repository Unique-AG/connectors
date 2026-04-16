import { Module } from '@nestjs/common';
import { AMQPModule } from '~/amqp/amqp.module';
import { DrizzleModule } from '~/db/drizzle.module';
import { FullSyncSchedulerService } from './full-sync-scheduler.service';
import { LiveCatchupSchedulerService } from './live-catchup-scheduler.service';
import { SyncOnFilterChangeService } from './sync-on-filter-change.service';

@Module({
  imports: [DrizzleModule, AMQPModule],
  providers: [LiveCatchupSchedulerService, SyncOnFilterChangeService, FullSyncSchedulerService],
  exports: [LiveCatchupSchedulerService, SyncOnFilterChangeService, FullSyncSchedulerService],
})
export class SyncRecoveryModule {}
