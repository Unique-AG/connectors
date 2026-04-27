import { Module } from '@nestjs/common';
import { ScheduleModule } from '@nestjs/schedule';
import { HealthModule } from '../health/health.module';
import { TenantModule } from '../tenant';
import { TenantSyncScheduler } from './tenant-sync.scheduler';

@Module({
  imports: [ScheduleModule.forRoot(), TenantModule, HealthModule],
  providers: [TenantSyncScheduler],
})
export class SchedulerModule {}
