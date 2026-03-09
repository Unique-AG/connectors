import { relations } from 'drizzle-orm';
import { integer, jsonb, pgEnum, pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { InboxConfigurationMailFilters } from './inbox-configuration-mail-filters.dto';
import { userProfiles } from '../user-profiles.table';

export const inboxSyncState = pgEnum('inbox_sync_state', ['idle', 'running', 'failed']);

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

  filters: jsonb(`filters`).$type<InboxConfigurationMailFilters>().notNull(),
  lastFullSyncRunAt: timestamp(`last_full_sync_run_at`),
  syncState: inboxSyncState(`sync_state`).notNull().default('idle'),
  syncStartedAt: timestamp(`sync_started_at`),
  messagesFromMicrosoft: integer(`messages_from_microsoft`).default(0),
  messagesQueuedForSync: integer(`messages_queued_for_sync`).default(0),
  messagesProcessed: integer(`messages_processed`).default(0),

  ...timestamps,
});

export type InboxConfiguration = typeof inboxConfiguration.$inferSelect;

export const inboxConfigurationRelations = relations(inboxConfiguration, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [inboxConfiguration.userProfileId],
    references: [userProfiles.id],
  }),
}));
