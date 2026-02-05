import { relations } from 'drizzle-orm';
import { index, pgEnum, pgTable, timestamp, text, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const emailSyncStatus = pgEnum('email_sync_status', ['active', 'paused', 'stopped']);

export const emailSyncConfigs = pgTable(
  'email_sync_configs',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('email_sync').toString()),
    userProfileId: varchar()
      .notNull()
      .unique()
      .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
    status: emailSyncStatus().notNull().default('active'),
    syncFromDate: timestamp().notNull(),
    deltaToken: text(),
    nextLink: text(),
    lastSyncAt: timestamp(),
    lastError: text(),

    ...timestamps,
  },
  (t) => [index('email_sync_configs_user_profile_id_idx').on(t.userProfileId)],
);

export const emailSyncConfigRelations = relations(emailSyncConfigs, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [emailSyncConfigs.userProfileId],
    references: [userProfiles.id],
  }),
}));

export type EmailSyncConfig = typeof emailSyncConfigs.$inferSelect;
export type NewEmailSyncConfig = typeof emailSyncConfigs.$inferInsert;
