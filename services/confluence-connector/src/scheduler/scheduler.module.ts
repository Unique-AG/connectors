import { Module } from '@nestjs/common';
import { ScheduleModule } from '@nestjs/schedule';
import { TenantSyncScheduler } from './tenant-sync.scheduler';

@Module({
  imports: [ScheduleModule.forRoot()],
  providers: [TenantSyncScheduler],
})
export class SchedulerModule {}
