import { Module } from '@nestjs/common';
import { SubscriptionModule } from '~/email-sync/subscriptions/subscription.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { ListCategoriesQuery } from './list-categories.query';

const QUERIES = [ListCategoriesQuery];

@Module({
  imports: [MsGraphModule, SubscriptionModule],
  providers: [...QUERIES],
  exports: [...QUERIES],
})
export class CategoriesModule {}
