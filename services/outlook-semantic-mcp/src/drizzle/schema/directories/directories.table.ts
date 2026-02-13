import {
  AnyPgColumn,
  pgEnum,
  pgTable,
  unique,
  varchar,
  boolean,
} from "drizzle-orm/pg-core";
import { timestamps } from "../../timestamps.columns";
import { userProfiles } from "../user-profiles.table";
import { relations } from "drizzle-orm";
import { typeid } from "typeid-js";

const directoryTypes = [
  "Archive",
  "Deleted Items",
  "Drafts",
  "Inbox",
  "Junk Email",
  "Outbox",
  "Sent Items",
  "Conversation History",
  "Recoverable Items Deletions",
  "Clutter",
  "User Defined Directory",
] as const;

export const directoryType = pgEnum("directory_internal_type", directoryTypes);

export type DirectoryType = (typeof directoryTypes)[number];

export type SystemDirectoryType = Exclude<
  DirectoryType,
  "User Defined Directory"
>;

export const SystemDirectoriesIgnoredForSync: DirectoryType[] = [
  "Deleted Items",
  "Junk Email",
  "Recoverable Items Deletions",
  "Clutter",
];

export type Directory = typeof directories.$inferSelect;

export const directories = pgTable(
  "directories",
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid("irectory").toString()),
    internalType: directoryType().notNull(),
    providerDirectoryId: varchar().notNull(),
    displayName: varchar().notNull(),
    parentId: varchar().references((): AnyPgColumn => directories.id, {
      onDelete: "cascade",
      onUpdate: "cascade",
    }),
    ignoreForSync: boolean(),
    // References
    userProfileId: varchar()
      .notNull()
      .references(() => userProfiles.id, {
        onDelete: "cascade",
        onUpdate: "cascade",
      }),

    ...timestamps,
  },
  (t) => [
    unique("single_directory_per_user_profile").on(
      t.userProfileId,
      t.providerDirectoryId,
    ),
  ],
);

export const directoriesRelations = relations(directories, ({ one, many }) => ({
  parent: one(directories, {
    fields: [directories.parentId],
    references: [directories.id],
    relationName: "parentChild",
  }),
  children: many(directories, { relationName: "parentChild" }),
  userProfile: one(userProfiles, {
    fields: [directories.userProfileId],
    references: [userProfiles.id],
  }),
}));
