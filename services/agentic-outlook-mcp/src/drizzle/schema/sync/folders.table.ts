import { relations } from 'drizzle-orm';
import { integer, pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../auth';
import { emails } from './emails.table';
import { syncJobs } from './sync-jobs.table';

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
  activatedAt: timestamp(),
  deactivatedAt: timestamp(),
  lastSyncedAt: timestamp(),

  // References
  userProfileId: varchar()
    .notNull()
    .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
  ...timestamps,
  syncJobId: varchar()
    .notNull()
    .references(() => syncJobs.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
});

export const folderRelations = relations(folders, ({ one, many }) => ({
  userProfile: one(userProfiles, {
    fields: [folders.userProfileId],
    references: [userProfiles.id],
  }),
  syncJob: one(syncJobs, {
    fields: [folders.syncJobId],
    references: [syncJobs.id],
  }),
  emails: many(emails),
}));