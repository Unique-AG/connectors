import { relations } from "drizzle-orm";
import {
  jsonb,
  pgEnum,
  pgTable,
  timestamp,
  unique,
  varchar,
} from "drizzle-orm/pg-core";
import { typeid } from "typeid-js";
import { timestamps } from "../../timestamps.columns";
import { userProfiles } from "../user-profiles.table";

export const emailSyncStats = pgTable("subscriptions", {
  id: varchar()
    .primaryKey()
    .$default(() => typeid("subscription").toString()),
  startedAt: timestamp().notNull(),
  finishedSchedulingMessagesAt: timestamp(),
  // References
  userProfileId: varchar()
    .notNull()
    .references(() => userProfiles.id, {
      onDelete: "cascade",
      onUpdate: "cascade",
    })
    .unique(),
  filters: jsonb(),
  ...timestamps,
});

export type EmailSyncStats = typeof emailSyncStats.$inferSelect;
