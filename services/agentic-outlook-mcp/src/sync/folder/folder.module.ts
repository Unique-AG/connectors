import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { SubscriptionModule } from '../subscription/subscription.module';
import { FolderService } from './folder.service';

@Module({
  imports: [DrizzleModule, MsGraphModule, SubscriptionModule],
  providers: [FolderService],
  exports: [FolderService],
})
export class FolderModule {}
