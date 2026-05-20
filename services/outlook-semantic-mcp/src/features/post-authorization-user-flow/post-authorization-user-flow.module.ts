import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { DirectoriesSyncModule } from '../directories-sync/directories-sync.module';
import { SubscriptionModule } from '../subscriptions/subscription.module';
import { PostAuthorizationListener } from './post-authorization.listener';
import { InboxDeletingQueryModule } from '../delete-inbox/inbox-deleting-query.module';

@Module({
  imports: [ConfigModule, SubscriptionModule, DirectoriesSyncModule, InboxDeletingQueryModule],
  providers: [PostAuthorizationListener],
})
export class PostAuthorizationUserFlowModule {}
