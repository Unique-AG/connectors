import { relations } from 'drizzle-orm';
import { pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const authorizationCodes = pgTable('authorization_codes', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('auth_code').toString()),
  code: varchar().notNull().unique(),
  userId: varchar().notNull(),
  clientId: varchar().notNull(),
  redirectUri: varchar().notNull(),
  codeChallenge: varchar().notNull(),
  codeChallengeMethod: varchar().notNull(),
  resource: varchar(),
  scope: varchar(),
  expiresAt: timestamp().notNull(),
  usedAt: timestamp(),
  userProfileId: varchar()
    .notNull()
    .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
  ...timestamps,
});

export const authorizationCodeRelations = relations(authorizationCodes, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [authorizationCodes.userProfileId],
    references: [userProfiles.id],
  }),
}));
