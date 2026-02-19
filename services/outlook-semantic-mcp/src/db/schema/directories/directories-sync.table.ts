import { relations } from 'drizzle-orm';
import { pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

export const directoriesSync = pgTable('directories_sync', {
  id: varchar(`id`)
    .primaryKey()
    .$default(() => typeid('directories_sync').toString()),
  deltaLink: varchar(`delta_link`),
  lastDeltaSyncRunedAt: timestamp(`last_delta_sync_runed_at`),
  lastDeltaChangeDetectedAt: timestamp(`last_delta_change_detected_at`),
  lastDirectorySyncRunnedAt: timestamp(`last_directory_sync_runned_at`),

  // References
  userProfileId: varchar(`user_profile_id`)
    .notNull()
    .unique()
    .references(() => userProfiles.id, {
      onDelete: 'cascade',
      onUpdate: 'cascade',
    }),

  ...timestamps,
});

export type DirectoriesSync = typeof directoriesSync.$inferSelect;

export const directoriesSyncRelations = relations(directoriesSync, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [directoriesSync.userProfileId],
    references: [userProfiles.id],
  }),
}));
