import { relations } from 'drizzle-orm';
import { pgEnum, pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../timestamps.columns';
import { userProfiles } from './user-profiles.table';

export const subscriptionForType = pgEnum('subscription_for_type', ['transcript']);

export const subscriptions = pgTable('subscriptions', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('subscription').toString()),
  subscriptionId: varchar().unique(),
  expiresAt: timestamp({ mode: 'string' }),
  
  // References
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
}));

export type Subscription = typeof subscriptions.$inferSelect;