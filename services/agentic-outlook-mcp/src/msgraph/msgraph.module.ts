import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { GraphClientFactory } from './graph-client.factory';
import { SubscriptionController } from './subscription.controller';
import { SubscriptionService } from './subscription.service';

@Module({
  imports: [DrizzleModule],
  controllers: [SubscriptionController],
  providers: [GraphClientFactory, SubscriptionService],
  exports: [GraphClientFactory, SubscriptionService],
})
export class MsGraphModule {}
