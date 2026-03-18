import { Module } from '@nestjs/common';
import { SubscriptionModule } from '~/features/subscriptions/subscription.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { CreateDraftEmailCommand } from './create-draft-email.command';

const COMMANDS = [CreateDraftEmailCommand];

@Module({
  imports: [MsGraphModule, SubscriptionModule, UniqueApiFeatureModule],
  providers: [...COMMANDS],
  exports: [...COMMANDS],
})
export class EmailManagementModule {}
