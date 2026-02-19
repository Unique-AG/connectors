import { relations } from 'drizzle-orm';
import { AnyPgColumn, boolean, pgEnum, pgTable, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

const directoryTypes = [
  'Archive',
  'Deleted Items',
  'Drafts',
  'Inbox',
  'Junk Email',
  'Outbox',
  'Sent Items',
  'Conversation History',
  'Recoverable Items Deletions',
  'Clutter',
  'User Defined Directory',
] as const;

export const directoryType = pgEnum('directory_internal_type', directoryTypes);

export type DirectoryType = (typeof directoryTypes)[number];

export type SystemDirectoryType = Exclude<DirectoryType, 'User Defined Directory'>;

export const SystemDirectoriesIgnoredForSync: DirectoryType[] = [
  'Deleted Items',
  'Junk Email',
  'Recoverable Items Deletions',
  'Clutter',
];

export type Directory = typeof directories.$inferSelect;

export const directories = pgTable(
  'directories',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('directory').toString()),
    internalType: directoryType(`internal_type`).notNull(),
    providerDirectoryId: varchar(`provider_directory_id`).notNull(),
    displayName: varchar(`display_name`).notNull(),
    parentId: varchar(`parent_id`).references((): AnyPgColumn => directories.id, {
      onDelete: 'cascade',
      onUpdate: 'cascade',
    }),
    ignoreForSync: boolean(`ignore_for_sync`),
    // References
    userProfileId: varchar(`user_profile_id`)
      .notNull()
      .references(() => userProfiles.id, {
        onDelete: 'cascade',
        onUpdate: 'cascade',
      }),

    ...timestamps,
  },
  (t) => [unique('single_directory_per_user_profile').on(t.userProfileId, t.providerDirectoryId)],
);

export const directoriesRelations = relations(directories, ({ one, many }) => ({
  parent: one(directories, {
    fields: [directories.parentId],
    references: [directories.id],
    relationName: 'parentChild',
  }),
  children: many(directories, { relationName: 'parentChild' }),
  userProfile: one(userProfiles, {
    fields: [directories.userProfileId],
    references: [userProfiles.id],
  }),
}));
