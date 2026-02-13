import { relations } from "drizzle-orm";
import { pgTable, timestamp, varchar } from "drizzle-orm/pg-core";
import { typeid } from "typeid-js";
import { timestamps } from "../../timestamps.columns";
import { userProfiles } from "../user-profiles.table";

export const authorizationCodes = pgTable("authorization_codes", {
  id: varchar(`id`)
    .primaryKey()
    .$default(() => typeid("auth_code").toString()),
  code: varchar(`code`).notNull().unique(),
  userId: varchar(`user_id`).notNull(),
  clientId: varchar(`client_id`).notNull(),
  redirectUri: varchar(`redirect_uri`).notNull(),
  codeChallenge: varchar(`code_challenge`).notNull(),
  codeChallengeMethod: varchar(`code_challenge_method`).notNull(),
  resource: varchar(`resource`),
  scope: varchar(`scope`),
  expiresAt: timestamp(`expires_at`).notNull(),
  usedAt: timestamp(`used_at`),
  userProfileId: varchar(`user_profile_id`)
    .notNull()
    .references(() => userProfiles.id, {
      onDelete: "cascade",
      onUpdate: "cascade",
    }),
  ...timestamps,
});

export const authorizationCodeRelations = relations(
  authorizationCodes,
  ({ one }) => ({
    userProfile: one(userProfiles, {
      fields: [authorizationCodes.userProfileId],
      references: [userProfiles.id],
    }),
  }),
);
