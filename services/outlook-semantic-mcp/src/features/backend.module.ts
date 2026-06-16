import { type DynamicModule, Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { isDebugMode, isMicrosoftGraphBackend } from '~/utils/backend-config.utils';
import { AdminModule } from './admin/admin.module';
import { AdminOpsTool } from './admin/admin-ops.tool';
import { CategoriesModule } from './categories/categories.module';
import { ListCategoriesTool } from './categories/list-categories.tool';
import { SearchEmailsTool, SearchModule } from './content';
import { OpenEmailModule } from './content/open-email/open-email.module';
import { OpenEmailTool } from './content/open-email/open-email.tool';
import { DelegatedAccessModule } from './delegated-access/delegated-access.module';
import { DelegatedAccessUtilsModule } from './delegated-access/delegated-access-utils.module';
import { DeleteInboxModule } from './delete-inbox/delete-inbox.module';
import { DeleteInboxDataTool } from './delete-inbox/delete-inbox-data.tool';
import { InboxDeletingQueryModule } from './delete-inbox/inbox-deleting-query.module';
import { DirectoriesSyncModule } from './directories-sync/directories-sync.module';
import { ListMailboxesAndDirectoriesTool } from './directories-sync/tools';
import { EmailManagementModule } from './email-management/email-management.module';
import { CreateDraftEmailTool } from './email-management/tools/create-draft-email.tool';
import { LookupContactsTool } from './email-management/tools/lookup-contacts.tool';
import { MailSubscriptionController } from './mail-subscription.controller';
import { PostAuthorizationUserFlowModule } from './post-authorization-user-flow/post-authorization-user-flow.module';
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
import { UserUtilsModule } from './user-utils/user-utils.module';

@Module({})
export class BackendModule {}

export function registerBackendModule(): DynamicModule {
  const isGraph = isMicrosoftGraphBackend();
  const isDebug = isDebugMode();

  const uniqueAndMicrosoftBackendCommonTools = [
    ListMailboxesAndDirectoriesTool,
    ListCategoriesTool,
    CreateDraftEmailTool,
    LookupContactsTool,
    SearchEmailsTool,
    OpenEmailTool,
  ];

  const uniqueOnlyTools = isGraph
    ? []
    : [
        SyncProgressTool,
        VerifyInboxConnectionTool,
        DeleteInboxDataTool,
        ReconnectInboxTool,
        ...(!isDebug
          ? []
          : [
              RunFullSyncTool,
              RestartFullSyncTool,
              PauseFullSyncTool,
              ResumeFullSyncTool,
              AdminOpsTool,
            ]),
      ];

  return {
    module: BackendModule,
    imports: [
      DrizzleModule,
      MsGraphModule,
      SubscriptionModule,
      DirectoriesSyncModule,
      CategoriesModule,
      EmailManagementModule,
      OpenEmailModule,
      InboxDeletingQueryModule,
      DeleteInboxModule,
      FullSyncModule,
      LiveCatchUpModule,
      ProcessEmailModule,
      SyncRecoveryModule,
      SearchModule,
      UniqueApiFeatureModule,
      UserUtilsModule,
      AdminModule,
      DelegatedAccessModule,
      PostAuthorizationUserFlowModule,
      DelegatedAccessUtilsModule,
    ],
    providers: [
      ...uniqueAndMicrosoftBackendCommonTools,
      ...uniqueOnlyTools,
      MailSubscriptionController,
    ],
    controllers: [MailSubscriptionController],
  };
}
