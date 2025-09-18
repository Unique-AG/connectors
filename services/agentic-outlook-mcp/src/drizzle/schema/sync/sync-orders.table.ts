import { pgTable, timestamp, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../auth';

export const syncOrders = pgTable('sync_orders', {
  id: varchar()
    .primaryKey()
    .$default(() => typeid('sync_order').toString()),
  userProfileId: varchar()
    .notNull()
    .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
  lastSyncedAt: timestamp(),
  syncToken: varchar(),
  deactivatedAt: timestamp(),
  ...timestamps,
});
