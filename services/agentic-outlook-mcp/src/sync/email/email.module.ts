import { Module } from '@nestjs/common';
import { EmailService } from './email.service';
import { EmailSyncService } from './email-sync.service';

@Module({
  imports: [],
  controllers: [],
  providers: [EmailService, EmailSyncService],
  exports: [EmailService, EmailSyncService],
})
export class EmailModule {}
