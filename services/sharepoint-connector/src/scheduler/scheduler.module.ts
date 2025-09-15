import { Module } from '@nestjs/common';
import { ScheduleModule } from '@nestjs/schedule';
import { SharepointScannerModule } from '../sharepoint-scanner/sharepoint-scanner.module';
import { SchedulerService } from './scheduler.service';

@Module({
  imports: [ScheduleModule.forRoot(), SharepointScannerModule],
  providers: [SchedulerService],
})
export class SchedulerModule {}
