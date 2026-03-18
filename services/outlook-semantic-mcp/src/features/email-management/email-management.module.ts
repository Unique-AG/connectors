import { Module } from '@nestjs/common';
import { SubscriptionModule } from '~/features/subscriptions/subscription.module';
import { SubscriptionUtilsModule } from '~/features/user-utils/subscription-utils.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { AddAttachmentsToDraftEmailCommand } from './add-attachments-to-draft-email.command';
import { CreateDraftEmailCommand } from './create-draft-email.command';
import { LookupContactsQuery } from './lookup-contacts.query';

const COMMANDS = [CreateDraftEmailCommand, AddAttachmentsToDraftEmailCommand];
const QUERIES = [LookupContactsQuery];

@Module({
  imports: [MsGraphModule, SubscriptionModule, SubscriptionUtilsModule, UniqueApiFeatureModule],
  providers: [...COMMANDS, ...QUERIES],
  exports: [...COMMANDS, ...QUERIES],
})
export class EmailManagementModule {}
