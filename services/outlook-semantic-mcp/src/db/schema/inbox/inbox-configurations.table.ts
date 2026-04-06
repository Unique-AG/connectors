import { relations } from 'drizzle-orm';
import {
  integer,
  jsonb,
  pgEnum,
  pgTable,
  text,
  timestamp,
  uuid,
  varchar,
} from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const inboxSyncState = pgEnum('inbox_sync_state', [
  'ready',
  'failed',
  'running',
  'paused',
  'waiting-for-ingestion',
]);

export const liveCatchUpState = pgEnum('live_catch_up_state', ['ready', 'running', 'failed']);

export const inboxConfigurations = pgTable('inbox_configurations', {
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
  // Full sync specific columns
  fullSyncState: inboxSyncState(`full_sync_state`).notNull().default('ready'),
  fullSyncHeartbeatAt: timestamp(`full_sync_heartbeat_at`).notNull().defaultNow(),
  fullSyncVersion: uuid(`full_sync_version`),
  fullSyncNextLink: text(`full_sync_next_link`),

  fullSyncBatchIndex: integer(`full_sync_batch_index`).notNull().default(0),
  fullSyncExpectedTotal: integer(`full_sync_expected_total`),
  fullSyncSkipped: integer(`full_sync_skipped`).notNull().default(0),
  fullSyncScheduledForIngestion: integer(`full_sync_scheduled_for_ingestion`).notNull().default(0),
  fullSyncFailedToUploadForIngestion: integer(`full_sync_failed_to_upload_for_ingestion`)
    .notNull()
    .default(0),

  fullSyncLastRunAt: timestamp(`full_sync_last_run_at`),
  fullSyncLastStartedAt: timestamp(`full_sync_last_started_at`),
  // Live catchup specific columns
  liveCatchUpState: liveCatchUpState(`live_catch_up_state`).notNull().default('ready'),
  liveCatchUpHeartbeatAt: timestamp(`live_catch_up_heartbeat_at`).notNull().defaultNow(),

  // Date watermarks for sync coordination
  oldestReceivedEmailDateTime: timestamp(`oldest_received_email_date_time`),
  newestReceivedEmailDateTime: timestamp(`newest_received_email_date_time`),
  newestLastModifiedDateTime: timestamp(`newest_last_modified_date_time`).notNull().defaultNow(),

  ...timestamps,
});

export type InboxConfiguration = typeof inboxConfigurations.$inferSelect;

export const inboxConfigurationRelations = relations(inboxConfigurations, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [inboxConfigurations.userProfileId],
    references: [userProfiles.id],
  }),
}));
