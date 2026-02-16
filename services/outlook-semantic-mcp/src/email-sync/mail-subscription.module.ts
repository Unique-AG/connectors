import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UNIQUE_API_FEATURE_MODULE } from '~/unique/unique-api.module';
import { DirectoriesSyncModule } from './directories-sync/directories-sync.module';
import { IngestionListener } from './ingestion.listener';
import { MailIngestionModule } from './mail-injestion/mail-ingestion.module';
import { MailSubscriptionController } from './mail-subscription.controller';
import { SubscriptionModule } from './subscriptions/subscription.module';

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    SubscriptionModule,
    MailIngestionModule,
    DirectoriesSyncModule,
    UNIQUE_API_FEATURE_MODULE,
  ],
  providers: [MailSubscriptionController, IngestionListener],
  controllers: [MailSubscriptionController],
})
export class MailSubscriptionModule {}
