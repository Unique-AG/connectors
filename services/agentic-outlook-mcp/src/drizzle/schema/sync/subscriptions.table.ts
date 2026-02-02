import { relations } from 'drizzle-orm';
import { pgEnum, pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';
import { folders } from './folders.table';

export const subscriptionForType = pgEnum('subscription_for_type', ['folder']);

export const subscriptions = pgTable('subscriptions', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('subscription').toString()),
  subscriptionId: varchar().unique(),
  resource: varchar().notNull(),
  expiresAt: timestamp({ mode: 'string' }),
  changeType: varchar().notNull().default('created,updated,deleted'),

  // References
  forId: varchar().notNull(),
  forType: subscriptionForType().notNull(),
  userProfileId: varchar()
    .notNull()
    .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
  ...timestamps,
});

export const subscriptionRelations = relations(subscriptions, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [subscriptions.userProfileId],
    references: [userProfiles.id],
  }),
  folder: one(folders, {
    fields: [subscriptions.forId, subscriptions.forType],
    references: [folders.id, folders.subscriptionType],
  }),
}));

export type Subscription = typeof subscriptions.$inferSelect;