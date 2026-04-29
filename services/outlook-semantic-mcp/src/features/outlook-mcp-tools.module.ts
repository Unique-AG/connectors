import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { AdminModule } from './admin/admin.module';
import { AdminOpsTool } from './admin/admin-ops.tool';
import { CategoriesModule } from './categories/categories.module';
import { ListCategoriesTool } from './categories/list-categories.tool';
import { OpenEmailTool, SearchEmailsTool, SearchModule } from './content';
import { DelegatedAccessModule } from './delegated-access/delegated-access.module';
import { DeleteInboxModule } from './delete-inbox/delete-inbox.module';
import { DeleteInboxDataTool } from './delete-inbox/delete-inbox-data.tool';
import { InboxDeletingQueryModule } from './delete-inbox/inbox-deleting-query.module';
import { DirectoriesSyncModule } from './directories-sync/directories-sync.module';
import { ListFoldersTool } from './directories-sync/tools';
import { EmailManagementModule } from './email-management/email-management.module';
import { CreateDraftEmailTool } from './email-management/tools/create-draft-email.tool';
import { LookupContactsTool } from './email-management/tools/lookup-contacts.tool';
import { MailSubscriptionController } from './mail-subscription.controller';
import { ProcessEmailModule } from './process-email/process-email.module';
import { SubscriptionModule } from './subscriptions/subscription.module';
import { ReconnectInboxTool, VerifyInboxConnectionTool } from './subscriptions/tools';
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
    ? [RunFullSyncTool, RestartFullSyncTool, PauseFullSyncTool, ResumeFullSyncTool, AdminOpsTool]
    : [];

const TOOLS = [
  ...DEBUG_MODE_TOOLS,
  ListFoldersTool,
  SyncProgressTool,
  VerifyInboxConnectionTool,
  ReconnectInboxTool,
  SearchEmailsTool,
  OpenEmailTool,
  ListCategoriesTool,
  CreateDraftEmailTool,
  LookupContactsTool,
  DeleteInboxDataTool,
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
    InboxDeletingQueryModule,
    DeleteInboxModule,
    CategoriesModule,
    EmailManagementModule,
    FullSyncModule,
    LiveCatchUpModule,
    ProcessEmailModule,
    DirectoriesSyncModule,
    SearchModule,
    UniqueApiFeatureModule,
    SyncRecoveryModule,
    AdminModule,
    DelegatedAccessModule,
  ],
  providers: [MailSubscriptionController, ...TOOLS],
  controllers: [MailSubscriptionController],
})
export class OutlookMcpToolsModule {}
