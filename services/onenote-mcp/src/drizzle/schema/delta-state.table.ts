import { relations } from 'drizzle-orm';
import { pgTable, text, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../timestamps.columns';
import { userProfiles } from './user-profiles.table';

export const deltaState = pgTable('delta_state', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('delta').toString()),
  userProfileId: varchar()
    .notNull()
    .unique()
    .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
  deltaLink: text().notNull(),
  lastSyncedAt: timestamp(),
  lastSyncStatus: varchar(),
  ...timestamps,
});

export const deltaStateRelations = relations(deltaState, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [deltaState.userProfileId],
    references: [userProfiles.id],
  }),
}));
