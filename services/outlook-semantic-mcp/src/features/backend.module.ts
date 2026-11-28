import { type DynamicModule, Module, type Type } from '@nestjs/common';
import { type FeaturesConfig, loadFeaturesConfig, type ToolName, toolsInGroup } from '~/config';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { AdminModule } from './admin/admin.module';
import { AdminOpsTool } from './admin/admin-ops.tool';
import { CalendarModule } from './calendar/calendar.module';
import { CancelEventTool } from './calendar/cancel-event.tool';
import { CheckAvailabilityTool } from './calendar/check-availability.tool';
import { CreateEventTool } from './calendar/create-event.tool';
import { ListCalendarsTool } from './calendar/list-calendars.tool';
import { RespondToInviteTool } from './calendar/respond-to-invite.tool';
import { SearchCalendarEventsTool } from './calendar/search-calendar-events.tool';
import { SuggestMeetingTimesTool } from './calendar/suggest-meeting-times.tool';
import { UpdateEventTool } from './calendar/update-event.tool';
import { CategoriesModule } from './categories/categories.module';
import { ListCategoriesTool } from './categories/list-categories.tool';
import { FetchNextSearchPagesTool, SearchEmailsTool, SearchModule } from './content';
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
import { AddAttachmentsToDraftEmailTool } from './email-management/tools/add-attachments-to-draft-email.tool';
import { CreateDraftEmailTool } from './email-management/tools/create-draft-email.tool';
import { LookupContactsTool } from './email-management/tools/lookup-contacts.tool';
import { RemoveAttachmentsFromDraftEmailTool } from './email-management/tools/remove-attachments-from-draft-email.tool';
import { UpdateDraftEmailTool } from './email-management/tools/update-draft-email.tool';
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

export const TOOL_CLASSES: Record<ToolName, Type> = {
  list_mailboxes_and_directories: ListMailboxesAndDirectoriesTool,
  list_categories: ListCategoriesTool,
  draft_email: CreateDraftEmailTool,
  update_draft_email: UpdateDraftEmailTool,
  add_attachments_to_draft_email: AddAttachmentsToDraftEmailTool,
  remove_attachments_from_draft_email: RemoveAttachmentsFromDraftEmailTool,
  lookup_contacts: LookupContactsTool,
  search_emails: SearchEmailsTool,
  fetch_next_search_pages: FetchNextSearchPagesTool,
  open_email: OpenEmailTool,
  sync_progress: SyncProgressTool,
  verify_inbox_connection: VerifyInboxConnectionTool,
  delete_inbox_data: DeleteInboxDataTool,
  reconnect_inbox: ReconnectInboxTool,
  run_full_sync: RunFullSyncTool,
  restart_full_sync: RestartFullSyncTool,
  pause_full_sync: PauseFullSyncTool,
  resume_full_sync: ResumeFullSyncTool,
  admin_ops: AdminOpsTool,
  list_calendars: ListCalendarsTool,
  search_calendar_events: SearchCalendarEventsTool,
  check_availability: CheckAvailabilityTool,
  suggest_meeting_times: SuggestMeetingTimesTool,
  respond_to_invite: RespondToInviteTool,
  create_event: CreateEventTool,
  update_event: UpdateEventTool,
  cancel_event: CancelEventTool,
};

/**
 * Every calendar tool, exported so the schema-harmony test runs over the real registration list
 * rather than a copy that can silently fall behind.
 */
export const CALENDAR_TOOLS = toolsInGroup('calendar').map((name) => TOOL_CLASSES[name]);

@Module({})
export class BackendModule {}

export function registerBackendModule(
  features: FeaturesConfig = loadFeaturesConfig(),
): DynamicModule {
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
      ...(features.calendar ? [CalendarModule] : []),
    ],
    providers: [
      ...[...features.tools].map((name) => TOOL_CLASSES[name]),
      MailSubscriptionController,
    ],
    controllers: [MailSubscriptionController],
  };
}
