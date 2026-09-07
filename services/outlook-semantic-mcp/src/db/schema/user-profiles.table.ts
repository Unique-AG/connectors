import { relations } from 'drizzle-orm';
import { jsonb, pgEnum, pgTable, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../timestamps.columns';
import { authorizationCodes } from './auth/authorization-codes.table';
import { tokens } from './auth/tokens.table';

const userProfileSourceValues = ['oauth', 'shared-mailbox', 'shared-mailbox-with-login'] as const;

export type UserProfileSource = (typeof userProfileSourceValues)[number];

export const userProfileSource = pgEnum('user_profile_source', userProfileSourceValues);

// Q1 — Address the mailbox as `users/{email}` rather than `me`.
// The Graph path is chosen before the token is resolved, so a delegate token
// plus `me` would ingest the delegate's own mailbox.
export const SOURCES_ADDRESSED_BY_EMAIL: readonly UserProfileSource[] = [
  'shared-mailbox',
  'shared-mailbox-with-login',
];

// Q3 — This profile holds usable credentials of its own.
// Distinct from Q1: a dual mailbox is addressed by email even though it has a token.
export const SOURCES_WITH_OWN_CREDENTIALS: readonly UserProfileSource[] = [
  'oauth',
  'shared-mailbox-with-login',
];

// Q4 / Q6 — Delegate grants for this owner must be full-access-only, and the
// shared-mailbox scheduler cadence / delegate-fallback branch applies.
// Same members as Q1 today; kept separate because Q1 (graph path) and Q7
// (whether "no delegates" is a problem) already diverge, and Q3 will diverge
// again the next time a source is added.
export const SOURCES_WITH_DELEGATE_FALLBACK: readonly UserProfileSource[] = [
  'shared-mailbox',
  'shared-mailbox-with-login',
];

// Q5 — This row is managed by the shared-mailbox sync (env-list ownership).
// Same members as Q1/Q4 today; the sync's removal path uses this as its
// ownership boundary and takes a different action per value.
export const SOURCES_OWNED_BY_SYNC: readonly UserProfileSource[] = [
  'shared-mailbox',
  'shared-mailbox-with-login',
];

/**
 * Compute the `source` to write on conflict. `null` means leave the existing
 * column untouched (the insert path uses the writer's own default).
 */
export function upgradedSource(
  existing: { source: UserProfileSource; hasToken: boolean } | undefined,
  listedAsSharedMailbox: boolean,
): UserProfileSource | null {
  if (!existing) {
    return null;
  }
  if (existing.source === 'shared-mailbox-with-login') {
    return null;
  }
  if (existing.source === 'shared-mailbox' && existing.hasToken) {
    return 'shared-mailbox-with-login';
  }
  if (existing.source === 'oauth' && existing.hasToken && listedAsSharedMailbox) {
    return 'shared-mailbox-with-login';
  }
  return null;
}

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

export type UserProfile = typeof userProfiles.$inferSelect;
