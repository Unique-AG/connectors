import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { InboxDeletingQueryModule } from '../delete-inbox/inbox-deleting-query.module';
import { DirectoriesSyncModule } from '../directories-sync/directories-sync.module';
import { SubscriptionModule } from '../subscriptions/subscription.module';
import { PostAuthorizationListener } from './post-authorization.listener';

@Module({
  imports: [ConfigModule, SubscriptionModule, DirectoriesSyncModule, InboxDeletingQueryModule],
  providers: [PostAuthorizationListener],
})
export class PostAuthorizationUserFlowModule {}
