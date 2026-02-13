import { pgTable, varchar } from "drizzle-orm/pg-core";
import { typeid } from "typeid-js";
import { timestamps } from "../../timestamps.columns";

export const oauthClients = pgTable("oauth_clients", {
  id: varchar(`id`)
    .primaryKey()
    .$default(() => typeid("oauth_client").toString()),
  clientId: varchar(`client_id`).notNull().unique(),
  clientSecret: varchar(`client_secret`),
  clientName: varchar(`client_name`).notNull(),
  clientDescription: varchar(`client_description`),
  logoUri: varchar(`logo_uri`),
  clientUri: varchar(`client_uri`),
  developerName: varchar(`developer_name`),
  developerEmail: varchar(`developer_email`),
  redirectUris: varchar(`redirect_uris`).array().notNull(),
  grantTypes: varchar(`grant_types`).array().notNull(),
  responseTypes: varchar(`response_types`).array().notNull(),
  tokenEndpointAuthMethod: varchar(`token_endpoint_auth_method`).notNull(),
  ...timestamps,
});
