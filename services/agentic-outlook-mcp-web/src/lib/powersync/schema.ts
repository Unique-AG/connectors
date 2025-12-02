import { DrizzleAppSchema } from '@powersync/drizzle-driver';
import {
  BuildQueryResult,
  DBQueryConfig,
  ExtractTablesWithRelations,
  relations,
} from 'drizzle-orm';
import { integer, sqliteTable, text } from 'drizzle-orm/sqlite-core';

const timestamps = {
  updatedAt: text('updated_at'),
  createdAt: text('created_at'),
};

export const userProfiles = sqliteTable('user_profiles', {
  id: text('id').primaryKey(),
  provider: text('provider'),
  providerUserId: text('provider_user_id'),
  username: text('username'),
  email: text('email'),
  displayName: text('display_name'),
  avatarUrl: text('avatar_url'),
  syncActivatedAt: text('sync_activated_at'),
  syncDeactivatedAt: text('sync_deactivated_at'),
  syncLastSyncedAt: text('sync_last_synced_at'),
  ...timestamps,
});

export const folders = sqliteTable('folders', {
  id: text('id').primaryKey(),
  name: text('name'),
  originalName: text('original_name'),
  folderId: text('folder_id'),
  parentFolderId: text('parent_folder_id'),
  childFolderCount: integer('child_folder_count'),
  totalItemCount: integer('total_item_count'),
  subscriptionId: text('subscription_id'),
  syncToken: text('sync_token'),
  activatedAt: text('activated_at'),
  deactivatedAt: text('deactivated_at'),
  lastSyncedAt: text('last_synced_at'),
  userProfileId: text('user_profile_id'),
  syncJobId: text('sync_job_id'),
  ...timestamps,
});

export const emails = sqliteTable('emails', {
  id: text('id').primaryKey(),
  messageId: text('message_id'),
  conversationId: text('conversation_id'),
  from: text('from'),
  subject: text('subject'),
  preview: text('preview'),
  bodyHtml: text('body_html'),
  processedBody: text('processed_body'),
  translatedBody: text('translated_body'),
  translatedSubject: text('translated_subject'),
  summarizedBody: text('summarized_body'),
  threadSummary: text('thread_summary'),
  isRead: integer('is_read', { mode: 'boolean' }),
  hasAttachments: integer('has_attachments', { mode: 'boolean' }),
  receivedAt: text('received_at'),
  ingestionLastError: text('ingestion_last_error'),
  ingestionLastAttemptAt: text('ingestion_last_attempt_at'),
  ingestionCompletedAt: text('ingestion_completed_at'),
  userProfileId: text('user_profile_id'),
  folderId: text('folder_id'),
  ...timestamps,
});

export const foldersRelations = relations(folders, ({ one, many }) => ({
  userProfile: one(userProfiles, {
    fields: [folders.userProfileId],
    references: [userProfiles.id],
  }),
  emails: many(emails),
}));

export const emailsRelations = relations(emails, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [emails.userProfileId],
    references: [userProfiles.id],
  }),
  folder: one(folders, {
    fields: [emails.folderId],
    references: [folders.id],
  }),
}));

export const userProfilesRelations = relations(userProfiles, ({ many }) => ({
  folders: many(folders),
  emails: many(emails),
}));

export const drizzleSchema = {
  userProfiles,
  userProfilesRelations,
  folders,
  foldersRelations,
  emails,
  emailsRelations,
};

export const schema = new DrizzleAppSchema(drizzleSchema);

type Schema = typeof drizzleSchema;
type TSchema = ExtractTablesWithRelations<Schema>;

export type IncludeRelation<TableName extends keyof TSchema> = DBQueryConfig<
  'one' | 'many',
  boolean,
  TSchema,
  TSchema[TableName]
>['with'];

export type InferResultType<
  TableName extends keyof TSchema,
  With extends IncludeRelation<TableName> | undefined = undefined,
> = BuildQueryResult<
  TSchema,
  TSchema[TableName],
  {
    with: With;
  }
>;

export type UserProfile = typeof userProfiles.$inferSelect;
export type Folder = typeof folders.$inferSelect;
export type Email = typeof emails.$inferSelect;
export type FolderWithEmails = Folder & { emails: Email[] };
