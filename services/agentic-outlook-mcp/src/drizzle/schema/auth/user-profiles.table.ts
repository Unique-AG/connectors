import { relations } from 'drizzle-orm';
import { jsonb, pgTable, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { emails, folders, syncJobs } from '../sync';
import { authorizationCodes } from './authorization-codes.table';
import { tokens } from './tokens.table';

export const userProfiles = pgTable(
  'user_profiles',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('user_profile').toString()),
    provider: varchar().notNull(),
    providerUserId: varchar().notNull(),
    username: varchar().notNull(),
    email: varchar(),
    displayName: varchar(),
    avatarUrl: varchar(),
    raw: jsonb(),
    accessToken: varchar(),
    refreshToken: varchar(),
    ...timestamps,
  },
  (table) => [unique().on(table.provider, table.providerUserId)],
);

export const userProfileRelations = relations(userProfiles, ({ many }) => ({
  authorizationCodes: many(authorizationCodes),
  tokens: many(tokens),
  folders: many(folders),
  emails: many(emails),
  syncJobs: many(syncJobs),
}));
