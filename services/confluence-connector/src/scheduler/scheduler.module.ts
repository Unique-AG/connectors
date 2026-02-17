import { Module } from '@nestjs/common';
import { ScheduleModule } from '@nestjs/schedule';
import { TenantModule } from '../tenant';
import { TenantSyncScheduler } from './tenant-sync.scheduler';

@Module({
  imports: [ScheduleModule.forRoot(), TenantModule],
  providers: [TenantSyncScheduler],
})
export class SchedulerModule {}
