import { relations } from 'drizzle-orm';
import { integer, pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { createInsertSchema, createUpdateSchema } from 'drizzle-zod';
import { typeid } from 'typeid-js';
import { z } from 'zod';
import { camelizeKeys } from '../../../utils/case-converter';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';
import { emails } from './emails.table';
import { subscriptionForType, subscriptions } from './subscriptions.table';

export const folders = pgTable('folders', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('folder').toString()),
  name: varchar().notNull(),
  originalName: varchar(),
  folderId: varchar().notNull().unique(),
  parentFolderId: varchar(),
  childFolderCount: integer().notNull().default(0),
  totalItemCount: integer().notNull().default(0),

  // Sync
  syncToken: varchar(),
  activatedAt: timestamp({ mode: 'string' }),
  deactivatedAt: timestamp({ mode: 'string' }),
  lastSyncedAt: timestamp({ mode: 'string' }),

  // References
  userProfileId: varchar()
    .notNull()
    .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
  ...timestamps,
  subscriptionType: subscriptionForType().default('folder'),
});

export const folderRelations = relations(folders, ({ one, many }) => ({
  userProfile: one(userProfiles, {
    fields: [folders.userProfileId],
    references: [userProfiles.id],
  }),
  emails: many(emails),
  subscription: one(subscriptions, {
    fields: [folders.id, folders.subscriptionType],
    references: [subscriptions.forId, subscriptions.forType],
  }),
}));

export type Folder = typeof folders.$inferSelect;
export type FolderInput = typeof folders.$inferInsert;
export const folderInsertSchema = createInsertSchema(folders);
export const folderInsertSchemaCamelized = z
  .unknown()
  .transform(camelizeKeys)
  .pipe(folderInsertSchema);

export const folderUpdateSchema = createUpdateSchema(folders);
export const folderUpdateSchemaCamelized = z
  .unknown()
  .transform(camelizeKeys)
  .pipe(folderUpdateSchema);
export type FolderUpdateZod = z.infer<typeof folderUpdateSchema>;
