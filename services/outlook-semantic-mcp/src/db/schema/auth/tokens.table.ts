import { relations } from 'drizzle-orm';
import { index, integer, pgEnum, pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const tokenType = pgEnum('token_type', ['ACCESS', 'REFRESH']);

export const tokens = pgTable(
  'tokens',
  {
    id: varchar(`id`)
      .notNull()
      .primaryKey()
      .$default(() => typeid('token').toString()),
    token: varchar(`token`).notNull().unique(),
    type: tokenType(`type`).notNull(),
    expiresAt: timestamp(`expires_at`).notNull(),
    userId: varchar(`user_id`).notNull(),
    clientId: varchar(`client_id`).notNull(),
    scope: varchar(`scope`).notNull(),
    resource: varchar(`resource`).notNull(),
    familyId: varchar(`family_id`),
    generation: integer(`generation`),
    usedAt: timestamp(`used_at`),
    userProfileId: varchar(`user_profile_id`)
      .notNull()
      .references(() => userProfiles.id, {
        onDelete: 'cascade',
        onUpdate: 'cascade',
      }),
    ...timestamps,
  },
  (table) => [
    index().on(table.familyId),
    index().on(table.expiresAt),
    index().on(table.userProfileId),
  ],
);

export const tokenRelations = relations(tokens, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [tokens.userProfileId],
    references: [userProfiles.id],
  }),
}));
