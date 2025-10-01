import { relations } from 'drizzle-orm';
import { index, integer, pgEnum, pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const tokenType = pgEnum('token_type', ['ACCESS', 'REFRESH']);

export const tokens = pgTable(
  'tokens',
  {
    id: varchar()
      .notNull()
      .primaryKey()
      .$default(() => typeid('token').toString()),
    token: varchar().notNull().unique(),
    type: tokenType().notNull(),
    expiresAt: timestamp().notNull(),
    userId: varchar().notNull(),
    clientId: varchar().notNull(),
    scope: varchar().notNull(),
    resource: varchar().notNull(),
    familyId: varchar(),
    generation: integer(),
    usedAt: timestamp(),
    userProfileId: varchar()
      .notNull()
      .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
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
