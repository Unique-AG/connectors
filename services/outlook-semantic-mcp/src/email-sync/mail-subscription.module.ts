import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueModule } from '~/unique/unique.module';
import { MailIngestionModule } from './mail-injestion/mail-ingestion.module';
import { MailSubscriptionController } from './mail-subscription.controller';
import { SubscriptionModule } from './subscriptions/subscription.module';

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueModule, SubscriptionModule, MailIngestionModule],
  providers: [MailSubscriptionController],
  controllers: [MailSubscriptionController],
})
export class MailSubscriptionModule {}
