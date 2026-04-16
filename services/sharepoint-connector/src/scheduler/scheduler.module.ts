import { Module } from '@nestjs/common';
import { ScheduleModule } from '@nestjs/schedule';
import { HealthModule } from '../health/health.module';
import { SharepointSynchronizationModule } from '../sharepoint-synchronization/sharepoint-synchronization.module';
import { SchedulerService } from './scheduler.service';

@Module({
  imports: [ScheduleModule.forRoot(), SharepointSynchronizationModule, HealthModule],
  providers: [SchedulerService],
})
export class SchedulerModule {}
