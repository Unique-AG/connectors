import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { EmailDaprModule } from './email-dapr/email-dapr.module';
import { FolderModule } from './folder/folder.module';
import { SubscriptionModule } from './subscription/subscription.module';
import { SyncController } from './sync.controller';
import { SyncService } from './sync.service';
import { UserModule } from './user/user.module';

@Module({
  imports: [DrizzleModule, UserModule, FolderModule, EmailDaprModule, SubscriptionModule],
  controllers: [SyncController],
  providers: [SyncService],
  exports: [UserModule, FolderModule, EmailDaprModule, SubscriptionModule],
})
export class SyncModule {}
