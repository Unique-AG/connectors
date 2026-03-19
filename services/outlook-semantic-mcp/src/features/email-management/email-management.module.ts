import { Module } from '@nestjs/common';
import { SubscriptionModule } from '~/features/subscriptions/subscription.module';
import { SubscriptionUtilsModule } from '~/features/user-utils/subscription-utils.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { AddAttachmentsToDraftEmailCommand } from './add-attachments-to-draft-email.command';
import { CreateDraftEmailCommand } from './create-draft-email.command';
import { LookupContactsQuery } from './lookup-contacts.query';
import { UploadInMemoryAttachmentCommand } from './email-attachments/upload-in-memory-attachment.command';
import { StreamUniqueAttachmentCommand } from './email-attachments/stream-unique-attachment.command';

const COMMANDS = [
  CreateDraftEmailCommand,
  AddAttachmentsToDraftEmailCommand,
  UploadInMemoryAttachmentCommand,
  StreamUniqueAttachmentCommand,
];
const QUERIES = [LookupContactsQuery];

@Module({
  imports: [MsGraphModule, SubscriptionModule, SubscriptionUtilsModule, UniqueApiFeatureModule],
  providers: [...COMMANDS, ...QUERIES],
  exports: [...COMMANDS, ...QUERIES],
})
export class EmailManagementModule {}
