import { Module } from '@nestjs/common';
import { ScheduleModule } from '@nestjs/schedule';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueModule } from '~/unique/unique.module';
import { EmailSyncScheduler } from './email-sync.scheduler';
import { EmailSyncService } from './email-sync.service';
import { GetEmailSyncStatusTool, StartEmailSyncTool, StopEmailSyncTool } from './tools';

@Module({
  imports: [ScheduleModule.forRoot(), DrizzleModule, MsGraphModule, UniqueModule],
  providers: [
    EmailSyncService,
    EmailSyncScheduler,
    StartEmailSyncTool,
    GetEmailSyncStatusTool,
    StopEmailSyncTool,
  ],
  exports: [EmailSyncService],
})
export class EmailSyncModule {}
