import { relations } from 'drizzle-orm';
import { integer, jsonb, pgEnum, pgTable, timestamp, uuid, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const inboxSyncState = pgEnum('inbox_sync_state', [
  'full-sync-finished',
  'running',
  'failed',
  'fetching-emails',
  'performing-file-diff',
  'processing-file-diff-changes',
]);

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
  fullSyncState: inboxSyncState(`full_sync_state`).notNull().default('full-sync-finished'),
  lastFullSyncStartedAt: timestamp(`last_full_sync_started_at`),
  fullSyncVersion: uuid(`full_sync_version`),
  messagesFromMicrosoft: integer(`messages_from_microsoft`).notNull().default(0),
  messagesQueuedForSync: integer(`messages_queued_for_sync`).notNull().default(0),
  messagesProcessed: integer(`messages_processed`).notNull().default(0),

  ...timestamps,
});

export type InboxConfiguration = typeof inboxConfiguration.$inferSelect;

export const inboxConfigurationRelations = relations(inboxConfiguration, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [inboxConfiguration.userProfileId],
    references: [userProfiles.id],
  }),
}));
