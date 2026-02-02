import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { EmailModule } from './email/email.module';
import { FolderModule } from './folder/folder.module';
import { SubscriptionModule } from './subscription/subscription.module';
import { SyncController } from './sync.controller';
import { SyncService } from './sync.service';
import { UserModule } from './user/user.module';

@Module({
  imports: [DrizzleModule, UserModule, FolderModule, SubscriptionModule, EmailModule],
  controllers: [SyncController],
  providers: [SyncService],
  exports: [UserModule, FolderModule, SubscriptionModule],
})
export class SyncModule {}
