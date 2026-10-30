import { Module } from '@nestjs/common';
import { GraphUtilsModule } from '~/features/graph-utils/graph-utils.module';
import { SubscriptionModule } from '~/features/subscriptions/subscription.module';
import { UserUtilsModule } from '~/features/user-utils/user-utils.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { AddAttachmentsToDraftEmailCommand } from './add-attachments-to-draft-email.command';
import { CreateDraftEmailCommand } from './create-draft-email.command';
import { StreamUniqueAttachmentCommand } from './email-attachments/stream-unique-attachment.command';
import { UploadInMemoryAttachmentCommand } from './email-attachments/upload-in-memory-attachment.command';
import { GetDraftStateQuery } from './get-draft-state.query';
import { LookupContactsQuery } from './lookup-contacts.query';
import { RemoveAttachmentsFromDraftEmailCommand } from './remove-attachments-from-draft-email.command';
import { UpdateDraftEmailCommand } from './update-draft-email.command';

const COMMANDS = [
  CreateDraftEmailCommand,
  AddAttachmentsToDraftEmailCommand,
  UploadInMemoryAttachmentCommand,
  StreamUniqueAttachmentCommand,
  UpdateDraftEmailCommand,
  RemoveAttachmentsFromDraftEmailCommand,
];
const QUERIES = [LookupContactsQuery, GetDraftStateQuery];

@Module({
  imports: [
    MsGraphModule,
    GraphUtilsModule,
    SubscriptionModule,
    UserUtilsModule,
    UniqueApiFeatureModule,
  ],
  providers: [...COMMANDS, ...QUERIES],
  exports: [...COMMANDS, ...QUERIES],
})
export class EmailManagementModule {}
