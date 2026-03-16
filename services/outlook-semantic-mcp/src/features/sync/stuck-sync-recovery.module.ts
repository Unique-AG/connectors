import { Module } from '@nestjs/common';
import { AMQPModule } from '~/amqp/amqp.module';
import { DrizzleModule } from '~/db/drizzle.module';
import { StuckSyncRecoveryService } from './stuck-sync-recovery.service';
import { SyncOnFilterChangeService } from './sync-on-filter-change.service';
@Module({
  imports: [DrizzleModule, AMQPModule],
  providers: [StuckSyncRecoveryService, SyncOnFilterChangeService],
  exports: [StuckSyncRecoveryService, SyncOnFilterChangeService],
})
export class FullSyncModule {}
