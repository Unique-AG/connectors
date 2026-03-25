import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { CategoriesModule } from './categories/categories.module';
import { ListCategoriesTool } from './categories/list-categories.tool';
import { OpenEmailTool, SearchEmailsTool, SearchModule } from './content';
import { DirectoriesSyncModule } from './directories-sync/directories-sync.module';
import { ListFoldersTool } from './directories-sync/tools';
import { EmailManagementModule } from './email-management/email-management.module';
import { CreateDraftEmailTool } from './email-management/tools/create-draft-email.tool';
import { LookupContactsTool } from './email-management/tools/lookup-contacts.tool';
import { IngestionListener } from './mail-ingestion/ingestion.listener';
import { MailIngestionModule } from './mail-ingestion/mail-ingestion.module';
import { MailSubscriptionController } from './mail-subscription.controller';
import { SubscriptionModule } from './subscriptions/subscription.module';
import {
  ReconnectInboxTool,
  RemoveInboxConnectionTool,
  VerifyInboxConnectionTool,
} from './subscriptions/tools';
import {
  PauseFullSyncTool,
  RestartFullSyncTool,
  ResumeFullSyncTool,
  RunFullSyncTool,
  SyncProgressTool,
} from './sync/full-sync';
import { FullSyncModule } from './sync/full-sync/full-sync.module';
import { LiveCatchUpModule } from './sync/live-catch-up/live-catch-up.module';
import { SyncRecoveryModule } from './sync/sync-recovery.module';

const DEBUG_MODE_TOOLS =
  process.env.MCP_DEBUG_MODE === 'enabled'
    ? [RunFullSyncTool, RestartFullSyncTool, PauseFullSyncTool, ResumeFullSyncTool]
    : [];

const TOOLS = [
  ...DEBUG_MODE_TOOLS,
  ListFoldersTool,
  SyncProgressTool,
  VerifyInboxConnectionTool,
  ReconnectInboxTool,
  RemoveInboxConnectionTool,
  SearchEmailsTool,
  OpenEmailTool,
  ListCategoriesTool,
  CreateDraftEmailTool,
  LookupContactsTool,
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
    LiveCatchUpModule,
    MailIngestionModule,
    DirectoriesSyncModule,
    SearchModule,
    UniqueApiFeatureModule,
    SyncRecoveryModule,
  ],
  providers: [MailSubscriptionController, IngestionListener, ...TOOLS],
  controllers: [MailSubscriptionController],
})
export class OutlookMcpToolsModule {}
