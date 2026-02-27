import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { CategoriesModule } from './categories/categories.module';
import { ListCategoriesTool } from './categories/list-categories.tool';
import { OpenEmailTool, SearchEmailsTool, SearchModule } from './content';
import { DirectoriesSyncModule } from './directories-sync/directories-sync.module';
import { ListFoldersTool } from './directories-sync/tools';
import { CreateDraftEmailTool } from './email-management/create-draft-email.tool';
import { EmailManagementModule } from './email-management/email-management.module';
import { RunFullSyncTool } from './full-sync';
import { FullSyncModule } from './full-sync/full-sync.module';
import { IngestionListener } from './ingestion.listener';
import { MailIngestionModule } from './mail-ingestion/mail-ingestion.module';
import { MailSubscriptionController } from './mail-subscription.controller';
import { SubscriptionModule } from './subscriptions/subscription.module';
import {
  ConnectInboxTool,
  RemoveInboxConnectionTool,
  VerifyInboxConnectionTool,
} from './subscriptions/tools';

const TOOLS = [
  ListFoldersTool,
  RunFullSyncTool,
  VerifyInboxConnectionTool,
  ConnectInboxTool,
  RemoveInboxConnectionTool,
  SearchEmailsTool,
  OpenEmailTool,
  ListCategoriesTool,
  CreateDraftEmailTool,
];

// We declare all tools / controllers into one module for simplicity, we could declare each tool
// in the module where it's business logic is but this would break business logic reusability instead
// we would need separated nestjs modules for controllers / tools to keep the business logic reusable.
// Right now this creates to much boilerplate once the number of tool will grow we can consider organizing
// them differently.
@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    SubscriptionModule,
    CategoriesModule,
    EmailManagementModule,
    FullSyncModule,
    MailIngestionModule,
    DirectoriesSyncModule,
    SearchModule,
    UniqueApiFeatureModule,
  ],
  providers: [MailSubscriptionController, IngestionListener, ...TOOLS],
  controllers: [MailSubscriptionController],
})
export class OutlookMcpToolsModule {}
