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
export class OutlookMcpToolsModules {}
