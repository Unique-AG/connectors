import { relations } from 'drizzle-orm';
import { type AnyPgColumn, boolean, jsonb, pgTable, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const mailFolders = pgTable(
  'mail_folders',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('mail_folder').toString()),
    displayName: varchar().notNull(),
    parentId: varchar().references((): AnyPgColumn => mailFolders.id, {
      onDelete: 'cascade',
      onUpdate: 'cascade',
    }),
    microsoftId: varchar().notNull(),
    uniqueScopeId: varchar().unique().notNull(),
    isSystemFolder: boolean().default(false).notNull(),
    debugData: jsonb(),

    // References
    userProfileId: varchar()
      .notNull()
      .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),

    ...timestamps,
  },
  (t) => [unique('unique_user_microsoft_folder').on(t.userProfileId, t.microsoftId)],
);

export const mailFolderRelations = relations(mailFolders, ({ one, many }) => ({
  parent: one(mailFolders, {
    fields: [mailFolders.parentId],
    references: [mailFolders.id],
    relationName: 'parentChild',
  }),
  children: many(mailFolders, { relationName: 'parentChild' }),
  userProfile: one(userProfiles, {
    fields: [mailFolders.userProfileId],
    references: [userProfiles.id],
  }),
}));

export type MailFolder = typeof mailFolders.$inferSelect;
