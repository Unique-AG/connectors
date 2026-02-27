import { relations } from 'drizzle-orm';
import { jsonb, pgTable, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../timestamps.columns';
import { authorizationCodes } from './auth/authorization-codes.table';
import { tokens } from './auth/tokens.table';

export const userProfiles = pgTable(
  'user_profiles',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('user_profile').toString()),
    provider: varchar(`provider`).notNull(),
    providerUserId: varchar(`provider_user_id`).notNull(),
    username: varchar(`username`).notNull(),
    // Service users have no emails, that's why email is nullable in this table. Right now I think we will
    // never have a null in this column but we inherited this from microsoft graph api, and we want
    // to move have a first version of the outlook semantic mcp. We should correct the types once we know
    // exactly what we get from mcp oath.
    email: varchar(`email`),
    displayName: varchar(`display_name`),
    avatarUrl: varchar(`avatar_url`),
    raw: jsonb(`raw`),
    accessToken: varchar(`access_token`),
    refreshToken: varchar(`refresh_token`),
    ...timestamps,
  },
  (table) => [unique().on(table.provider, table.providerUserId)],
);

export const userProfileRelations = relations(userProfiles, ({ many }) => ({
  authorizationCodes: many(authorizationCodes),
  tokens: many(tokens),
}));

export type UserProfile = typeof userProfiles.$inferSelect;
