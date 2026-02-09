import { pgTable, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';

export const oauthClients = pgTable('oauth_clients', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('oauth_client').toString()),
  clientId: varchar().notNull().unique(),
  clientSecret: varchar(),
  clientName: varchar().notNull(),
  clientDescription: varchar(),
  logoUri: varchar(),
  clientUri: varchar(),
  developerName: varchar(),
  developerEmail: varchar(),
  redirectUris: varchar().array().notNull(),
  grantTypes: varchar().array().notNull(),
  responseTypes: varchar().array().notNull(),
  tokenEndpointAuthMethod: varchar().notNull(),
  ...timestamps,
});
