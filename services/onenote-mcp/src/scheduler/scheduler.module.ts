import { Module } from '@nestjs/common';
import { OneNoteModule } from '~/onenote/onenote.module';
import { SchedulerService } from './scheduler.service';

@Module({
  imports: [OneNoteModule],
  providers: [SchedulerService],
})
export class SchedulerModule {}
