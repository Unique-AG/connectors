import { relations } from 'drizzle-orm';
import { integer, pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { z } from 'zod';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';
import { emails } from './emails.table';

export const folders = pgTable('folders', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('folder').toString()),
  name: varchar().notNull(),
  originalName: varchar(),
  folderId: varchar().notNull().unique(),
  parentFolderId: varchar(),
  childFolderCount: integer().notNull().default(0),

  // Sync
  subscriptionId: varchar(),
  syncToken: varchar(),
  activatedAt: timestamp({ mode: "string" }),
  deactivatedAt: timestamp({ mode: "string" }),
  lastSyncedAt: timestamp({ mode: "string" }),

  // References
  userProfileId: varchar()
    .notNull()
    .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
  ...timestamps,
});

export const folderRelations = relations(folders, ({ one, many }) => ({
  userProfile: one(userProfiles, {
    fields: [folders.userProfileId],
    references: [userProfiles.id],
  }),
  emails: many(emails),
}));

// TODO: Ideally create with drizzle-zod, but it does not work yet...
export const folderSchema = z.object({
  id: z.string(),
  name: z.string(),
  originalName: z.string().nullable(),
  folderId: z.string(),
  parentFolderId: z.string().nullable(),
  childFolderCount: z.number().nullable(),
  subscriptionId: z.string().nullable(),
  syncToken: z.string().nullable(),
  activatedAt: z.iso.datetime().nullable(),
  deactivatedAt: z.iso.datetime().nullable(),
  lastSyncedAt: z.iso.datetime().nullable(),
  userProfileId: z.string(),
  createdAt: z.iso.datetime().nullable(),
  updatedAt: z.iso.datetime().nullable(),
});
export const folderArraySchema = z.array(folderSchema);

export type FolderInput = typeof folders.$inferInsert;