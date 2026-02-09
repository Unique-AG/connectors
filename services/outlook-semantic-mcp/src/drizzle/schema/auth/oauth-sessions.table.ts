import { pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';

export const oauthSessions = pgTable('oauth_sessions', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('oauth_session').toString()),
  sessionId: varchar().notNull().unique(),
  state: varchar().notNull(),
  clientId: varchar(),
  redirectUri: varchar(),
  codeChallenge: varchar(),
  codeChallengeMethod: varchar(),
  oauthState: varchar(),
  scope: varchar(),
  resource: varchar(),
  expiresAt: timestamp(),
  ...timestamps,
});
