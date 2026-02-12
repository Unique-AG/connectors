import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueModule } from '~/unique/unique.module';
import { DirectoriesSyncModule } from './directories-sync/directories-sync.module';
import { IngestionListener } from './ingestion.listener';
import { MailIngestionModule } from './mail-injestion/mail-ingestion.module';
import { MailSubscriptionController } from './mail-subscription.controller';
import { SubscriptionModule } from './subscriptions/subscription.module';

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    UniqueModule,
    SubscriptionModule,
    MailIngestionModule,
    DirectoriesSyncModule,
  ],
  providers: [MailSubscriptionController, IngestionListener],
  controllers: [MailSubscriptionController],
})
export class MailSubscriptionModule {}
