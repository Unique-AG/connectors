import { Module } from '@nestjs/common';
import { ScheduleModule } from '@nestjs/schedule';
import { HttpClientModule } from '../http-client.module';
import { MsGraphModule } from '../msgraph/msgraph.module';
import { SharepointSynchronizationModule } from '../sharepoint-synchronization/sharepoint-synchronization.module';
import { SchedulerService } from './scheduler.service';

@Module({
  imports: [
    ScheduleModule.forRoot(),
    SharepointSynchronizationModule,
    MsGraphModule,
    HttpClientModule,
  ],
  providers: [SchedulerService],
})
export class SchedulerModule {}
