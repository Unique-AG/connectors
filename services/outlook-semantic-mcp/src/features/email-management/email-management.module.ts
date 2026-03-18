import { Module } from '@nestjs/common';
import { SubscriptionModule } from '~/features/subscriptions/subscription.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { CreateDraftEmailCommand } from './create-draft-email.command';
import { LookupContactsQuery } from './lookup-contacts.query';

const COMMANDS = [CreateDraftEmailCommand];
const QUERIES = [LookupContactsQuery];

@Module({
  imports: [MsGraphModule, SubscriptionModule, UniqueApiFeatureModule],
  providers: [...COMMANDS, ...QUERIES],
  exports: [...COMMANDS, ...QUERIES],
})
export class EmailManagementModule {}
