import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { DirectoriesSyncModule } from '../directories-sync/directories-sync.module';
import { GetSubscriptionStatusQuery } from './get-subscription-status.query';
import { SubscriptionCreateService } from './subscription-create.service';
import { SubscriptionReauthorizeService } from './subscription-reauthorize.service';
import { SubscriptionRemoveService } from './subscription-remove.service';
import { MailSubscriptionUtilsService } from './subscription-utils.service';

@Module({
  imports: [DrizzleModule, MsGraphModule, DirectoriesSyncModule],
  providers: [
    MailSubscriptionUtilsService,
    SubscriptionCreateService,
    SubscriptionReauthorizeService,
    SubscriptionRemoveService,
    GetSubscriptionStatusQuery,
  ],
  exports: [
    MailSubscriptionUtilsService,
    SubscriptionCreateService,
    SubscriptionReauthorizeService,
    SubscriptionRemoveService,
    GetSubscriptionStatusQuery,
  ],
})
export class SubscriptionModule {}
