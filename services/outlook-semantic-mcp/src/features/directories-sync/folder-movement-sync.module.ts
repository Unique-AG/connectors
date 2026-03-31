import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { MailIngestionModule } from '../mail-ingestion/mail-ingestion.module';
import { FolderMovementSyncCommand } from './folder-movement-sync.command';
import { FolderMovementSyncListener } from './folder-movement-sync.listener';
import { FolderMovementSyncSchedulerService } from './folder-movement-sync-scheduler.service';

@Module({
  imports: [DrizzleModule, MsGraphModule, MailIngestionModule],
  providers: [FolderMovementSyncCommand, FolderMovementSyncListener, FolderMovementSyncSchedulerService],
  exports: [FolderMovementSyncCommand],
})
export class FolderMovementSyncModule {}
