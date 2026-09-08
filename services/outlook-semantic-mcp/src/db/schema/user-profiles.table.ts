import { relations, sql } from 'drizzle-orm';
import { jsonb, pgEnum, pgTable, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../timestamps.columns';
import { authorizationCodes } from './auth/authorization-codes.table';
import { tokens } from './auth/tokens.table';

const userProfileSourceValues = ['oauth', 'shared-mailbox', 'shared-mailbox-with-login'] as const;

export type UserProfileSource = (typeof userProfileSourceValues)[number];

export const userProfileSource = pgEnum('user_profile_source', userProfileSourceValues);

// Address as `users/{email}` not `me` — path is chosen before the token.
export const SOURCES_ADDRESSED_BY_EMAIL: readonly UserProfileSource[] = [
  'shared-mailbox',
  'shared-mailbox-with-login',
];

// Profile has its own Graph tokens.
export const SOURCES_WITH_OWN_CREDENTIALS: readonly UserProfileSource[] = [
  'oauth',
  'shared-mailbox-with-login',
];

// May use a Full Access delegate after the mailbox's own token.
export const SOURCES_WITH_DELEGATE_FALLBACK: readonly UserProfileSource[] = [
  'shared-mailbox',
  'shared-mailbox-with-login',
];

// Owned by shared-mailbox env-list sync.
export const SOURCES_OWNED_BY_SYNC: readonly UserProfileSource[] = [
  'shared-mailbox',
  'shared-mailbox-with-login',
];

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
    source: userProfileSource('source').notNull().default('oauth'),
    ...timestamps,
  },
  (table) => [unique().on(table.provider, table.providerUserId)],
);

export const userProfileRelations = relations(userProfiles, ({ many }) => ({
  authorizationCodes: many(authorizationCodes),
  tokens: many(tokens),
}));

// Sync conflict: promote to dual only when the existing row already has a token.
export const sourceOnListedMailboxConflict = sql`
  CASE
    WHEN ${userProfiles.source} = 'shared-mailbox-with-login' THEN ${userProfiles.source}
    WHEN ${userProfiles.source} = 'shared-mailbox'
         AND ${userProfiles.accessToken} IS NOT NULL THEN 'shared-mailbox-with-login'
    WHEN ${userProfiles.source} = 'oauth'
         AND ${userProfiles.accessToken} IS NOT NULL THEN 'shared-mailbox-with-login'
    ELSE ${userProfiles.source}
  END
`;

// Login conflict: promote shared-mailbox to dual; leave oauth unchanged.
export const sourceOnLoginConflict = sql`
  CASE
    WHEN ${userProfiles.source} = 'shared-mailbox' THEN 'shared-mailbox-with-login'
    ELSE ${userProfiles.source}
  END
`;

export type UserProfile = typeof userProfiles.$inferSelect;
