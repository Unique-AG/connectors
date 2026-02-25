import { Module } from '@nestjs/common';
import { SubscriptionModule } from '~/email-sync/subscriptions/subscription.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { CreateDraftEmailCommand } from './create-draft-email.command';

const COMMANDS = [CreateDraftEmailCommand];

@Module({
  imports: [MsGraphModule, SubscriptionModule],
  providers: [...COMMANDS],
  exports: [...COMMANDS],
})
export class EmailManagementModule {}
