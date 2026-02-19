import { relations } from 'drizzle-orm';
import { jsonb, pgEnum, pgTable, timestamp, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const subscriptionInternalType = pgEnum('subscription_internal_type', ['mail_monitoring']);

export const subscriptions = pgTable(
  'subscriptions',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('subscription').toString()),
    subscriptionId: varchar(`subscription_id`).unique().notNull(),
    internalType: subscriptionInternalType(`internal_type`).notNull(),
    expiresAt: timestamp(`expires_at`).notNull(),
    lastFullSyncRunAt: timestamp(`last_full_sync_run_at`),
    filters: jsonb(`filters`),

    // References
    userProfileId: varchar(`user_profile_id`)
      .notNull()
      .references(() => userProfiles.id, {
        onDelete: 'cascade',
        onUpdate: 'cascade',
      }),

    ...timestamps,
  },
  (t) => [unique('single_subscription_for_internal_type').on(t.userProfileId, t.internalType)],
);

export const subscriptionRelations = relations(subscriptions, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [subscriptions.userProfileId],
    references: [userProfiles.id],
  }),
}));

export type Subscription = typeof subscriptions.$inferSelect;
