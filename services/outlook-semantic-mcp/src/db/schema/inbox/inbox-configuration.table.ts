import { relations, sql } from 'drizzle-orm';
import { jsonb, pgEnum, pgTable, text, timestamp, uuid, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const inboxSyncState = pgEnum('inbox_sync_state', ['ready', 'failed', 'fetching-emails']);

export const liveCatchUpState = pgEnum('live_catch_up_state', ['ready', 'running', 'failed']);

export const inboxConfiguration = pgTable('inbox_configuration', {
  id: varchar('id')
    .primaryKey()
    .$default(() => typeid('inbox_configuration').toString()),

  // References
  userProfileId: varchar(`user_profile_id`)
    .notNull()
    .unique()
    .references(() => userProfiles.id, {
      onDelete: 'cascade',
      onUpdate: 'cascade',
    }),

  filters: jsonb(`filters`).$type<Record<string, unknown>>().notNull(),
  lastFullSyncRunAt: timestamp(`last_full_sync_run_at`),
  fullSyncState: inboxSyncState(`full_sync_state`).notNull().default('ready'),
  lastFullSyncStartedAt: timestamp(`last_full_sync_started_at`),
  fullSyncVersion: uuid(`full_sync_version`),
  liveCatchUpState: liveCatchUpState(`live_catch_up_state`).notNull().default('ready'),
  fullSyncNextLink: text(`full_sync_next_link`),
  pendingLiveMessageIds: text(`pending_live_message_ids`).array().notNull().default(sql`'{}'`),

  // Date watermarks for sync coordination
  newestCreatedDateTime: timestamp(`newest_created_date_time`),
  oldestCreatedDateTime: timestamp(`oldest_created_date_time`),
  newestLastModifiedDateTime: timestamp(`newest_last_modified_date_time`),
  oldestLastModifiedDateTime: timestamp(`oldest_last_modified_date_time`),

  ...timestamps,
});

export type InboxConfiguration = typeof inboxConfiguration.$inferSelect;

export const inboxConfigurationRelations = relations(inboxConfiguration, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [inboxConfiguration.userProfileId],
    references: [userProfiles.id],
  }),
}));
