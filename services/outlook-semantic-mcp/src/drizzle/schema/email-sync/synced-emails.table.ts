import { relations } from 'drizzle-orm';
import { pgTable, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const syncedEmails = pgTable('synced_emails', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('synced_email').toString()),
  emailId: varchar().unique().notNull(),
  internetMessageId: varchar().notNull(),
  contentHash: varchar().notNull(),
  scopeId: varchar().notNull(),
  contentKey: varchar().notNull(),

  userProfileId: varchar()
    .notNull()
    .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),

  ...timestamps,
});

export const syncedEmailRelations = relations(syncedEmails, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [syncedEmails.userProfileId],
    references: [userProfiles.id],
  }),
}));

export type SyncedEmail = typeof syncedEmails.$inferSelect;
