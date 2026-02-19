import { pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';

export const oauthSessions = pgTable('oauth_sessions', {
  id: varchar(`id`)
    .primaryKey()
    .$default(() => typeid('oauth_session').toString()),
  sessionId: varchar(`session_id`).notNull().unique(),
  state: varchar(`state`).notNull(),
  clientId: varchar(`client_id`),
  redirectUri: varchar(`redirect_uri`),
  codeChallenge: varchar(`code_challenge`),
  codeChallengeMethod: varchar(`code_challenge_method`),
  oauthState: varchar(`oauth_state`),
  scope: varchar(`scope`),
  resource: varchar(`resource`),
  expiresAt: timestamp(`expires_at`),
  ...timestamps,
});
