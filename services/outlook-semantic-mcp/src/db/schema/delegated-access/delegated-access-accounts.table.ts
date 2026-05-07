import { relations } from 'drizzle-orm';
import { boolean, pgTable, timestamp, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const delegatedAccessAccounts = pgTable(
  'delegated_access_accounts',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('dap').toString()),
    delegateUserId: varchar(`delegate_user_id`)
      .notNull()
      .references(() => userProfiles.id, {
        onDelete: 'cascade',
        onUpdate: 'cascade',
      }),
    ownerUserId: varchar(`owner_user_id`)
      .notNull()
      .references(() => userProfiles.id, {
        onDelete: 'cascade',
        onUpdate: 'cascade',
      }),
    hasFullDelegatedAccess: boolean(`has_full_delegated_access`).notNull().default(false),
    lastDiscoveredAt: timestamp(`last_discovered_at`),
    lastVerifiedAt: timestamp(`last_verified_at`),

    ...timestamps,
  },
  (t) => [unique('unique_delegate_owner_pair').on(t.delegateUserId, t.ownerUserId)],
);

export const delegatedAccessPipelineRelations = relations(delegatedAccessAccounts, ({ one }) => ({
  delegateUser: one(userProfiles, {
    fields: [delegatedAccessAccounts.delegateUserId],
    references: [userProfiles.id],
    relationName: 'delegateUser',
  }),
  ownerUser: one(userProfiles, {
    fields: [delegatedAccessAccounts.ownerUserId],
    references: [userProfiles.id],
    relationName: 'ownerUser',
  }),
}));

export type DelegatedAccessPipeline = typeof delegatedAccessAccounts.$inferSelect;
