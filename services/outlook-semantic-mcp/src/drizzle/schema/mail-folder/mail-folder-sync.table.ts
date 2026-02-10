import { relations } from "drizzle-orm";
import { timestamp, pgTable, unique, varchar } from "drizzle-orm/pg-core";
import { timestamps } from "../../timestamps.columns";
import { userProfiles } from "../user-profiles.table";

export const mailFoldersSync = pgTable(
  "mail_folders_sync",
  {
    // References
    userProfileId: varchar()
      .notNull()
      .references(() => userProfiles.id, {
        onDelete: "cascade",
        onUpdate: "cascade",
      }),
    ...timestamps,
    systemFoldersSyncedAt: timestamp(),
    lastFullSyncDate: timestamp(),
    deltaLink: varchar(),
    nextDeltaLink: varchar(),
  },
  (t) => [unique("unique_user_microsoft_folder").on(t.userProfileId)],
);

export const mailFolderSyncRelations = relations(
  mailFoldersSync,
  ({ one }) => ({
    userProfile: one(userProfiles, {
      fields: [mailFoldersSync.userProfileId],
      references: [userProfiles.id],
    }),
  }),
);

export type MailFolderSync = typeof mailFoldersSync.$inferSelect;
