import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueModule } from '~/unique/unique.module';
import { SubscriptionCreateService } from './subscription-create.service';
import { SubscriptionReauthorizeService } from './subscription-reauthorize.service';
import { SubscriptionRemoveService } from './subscription-remove.service';
import {
  StartKbIntegrationTool,
  StopKbIntegrationTool,
  VerifyKbIntegrationStatusTool,
} from './tools';
import { MailSubscriptionUtilsService } from './subscription-utils.service';
import { MailSubscriptionController } from './mail-subscription.controller';

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueModule],
  providers: [
    MailSubscriptionUtilsService,
    SubscriptionCreateService,
    SubscriptionReauthorizeService,
    SubscriptionRemoveService,
    MailSubscriptionController,
    // KB Integration MCP Tools
    VerifyKbIntegrationStatusTool,
    StartKbIntegrationTool,
    StopKbIntegrationTool,
  ],
  controllers: [MailSubscriptionController],
})
export class SubscriptionModule {}
