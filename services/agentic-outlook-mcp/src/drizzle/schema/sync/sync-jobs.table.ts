import { InferSelectModel, relations } from 'drizzle-orm';
import { pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../auth';
import { folders } from './folders.table';

export const syncJobs = pgTable('sync_jobs', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('sync_job').toString()),

  lastSyncedAt: timestamp(),
  deactivatedAt: timestamp(),

  // References
  userProfileId: varchar()
    .notNull()
    .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
  ...timestamps,
});

export const syncJobRelations = relations(syncJobs, ({ one, many }) => ({
  userProfile: one(userProfiles, {
    fields: [syncJobs.userProfileId],
    references: [userProfiles.id],
  }),
  folders: many(folders),
}));

export type SyncJob = InferSelectModel<typeof syncJobs>;