import { DrizzleAppSchema } from '@powersync/drizzle-driver';
import { BuildQueryResult, DBQueryConfig, ExtractTablesWithRelations, relations } from 'drizzle-orm';
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
  ...timestamps,
});

export const userProfilesRelations = relations(userProfiles, ({ many }) => ({
  syncJobs: many(syncJobs),
  folders: many(folders),
  emails: many(emails),
}));

export const syncJobs = sqliteTable('sync_jobs', {
  id: text('id').primaryKey(),
  userProfileId: text('user_profile_id'),
  ...timestamps,
});

export const syncJobsRelations = relations(syncJobs, ({ one, many }) => ({
  userProfile: one(userProfiles, {
    fields: [syncJobs.userProfileId],
    references: [userProfiles.id],
  }),
  folders: many(folders),
}));

export const folders = sqliteTable('folders', {
  id: text('id').primaryKey(),
  name: text('name'),
  originalName: text('original_name'),
  folderId: text('folder_id'),
  parentFolderId: text('parent_folder_id'),
  childFolderCount: integer('child_folder_count'),
  subscriptionId: text('subscription_id'),
  syncToken: text('sync_token'),
  activatedAt: text('activated_at'),
  deactivatedAt: text('deactivated_at'),
  lastSyncedAt: text('last_synced_at'),
  userProfileId: text('user_profile_id'),
  syncJobId: text('sync_job_id'),
  ...timestamps,
});

export const foldersRelations = relations(folders, ({ one, many }) => ({
  userProfile: one(userProfiles, {
    fields: [folders.userProfileId],
    references: [userProfiles.id],
  }),
  syncJob: one(syncJobs, {
    fields: [folders.syncJobId],
    references: [syncJobs.id],
  }),
  emails: many(emails),
}));

export const emails = sqliteTable('emails', {
  id: text('id').primaryKey(),
  userProfileId: text('user_profile_id'),
  folderId: text('folder_id'),
});

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

export const drizzleSchema = {
  userProfiles,
  syncJobs,
  folders,
  emails,
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
export type SyncJob = typeof syncJobs.$inferSelect;
export type Folder = typeof folders.$inferSelect;
export type Email = typeof emails.$inferSelect;