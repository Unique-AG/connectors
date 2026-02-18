import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { SubscriptionCreateService } from './subscription-create.service';
import { SubscriptionReauthorizeService } from './subscription-reauthorize.service';
import { SubscriptionRemoveService } from './subscription-remove.service';
import { MailSubscriptionUtilsService } from './subscription-utils.service';
import {
  ConnectInboxTool,
  RemoveInboxConnectionTool,
  VerifyInboxConnectionTool,
} from './tools';

@Module({
  imports: [DrizzleModule, MsGraphModule],
  providers: [
    MailSubscriptionUtilsService,
    SubscriptionCreateService,
    SubscriptionReauthorizeService,
    SubscriptionRemoveService,
    VerifyInboxConnectionTool,
    ConnectInboxTool,
    RemoveInboxConnectionTool,
  ],
  exports: [
    MailSubscriptionUtilsService,
    SubscriptionCreateService,
    SubscriptionReauthorizeService,
    SubscriptionRemoveService,
  ],
})
export class SubscriptionModule {}
