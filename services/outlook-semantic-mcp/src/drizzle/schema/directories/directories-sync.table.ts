import { pgTable, varchar, timestamp } from "drizzle-orm/pg-core";
import { typeid } from "typeid-js";
import { userProfiles } from "../user-profiles.table";
import { timestamps } from "../../timestamps.columns";
import { relations } from "drizzle-orm";

export const directoriesSync = pgTable("directories_sync", {
  id: varchar()
    .primaryKey()
    .$default(() => typeid("directories_sync").toString()),
  deltaLink: varchar(),
  lastDeltaSyncRunedAt: timestamp(),
  lastDeltaChangeDetectedAt: timestamp(),
  lastDirectorySyncRunnedAt: timestamp(),

  // References
  userProfileId: varchar()
    .notNull()
    .unique()
    .references(() => userProfiles.id, {
      onDelete: "cascade",
      onUpdate: "cascade",
    }),

  ...timestamps,
});

export type DirectoriesSync = typeof directoriesSync.$inferSelect;

export const directoriesSyncRelations = relations(
  directoriesSync,
  ({ one, many }) => ({
    userProfile: one(userProfiles, {
      fields: [directoriesSync.userProfileId],
      references: [userProfiles.id],
    }),
  }),
);
