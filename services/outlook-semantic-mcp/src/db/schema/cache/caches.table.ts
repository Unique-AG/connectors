import { jsonb, pgTable, varchar } from 'drizzle-orm/pg-core';
import { timestamps } from '~/db/timestamps.columns';
import { CacheData } from './cache.data';

export const caches = pgTable('caches', {
  key: varchar().primaryKey(),
  data: jsonb(`data`).$type<CacheData>().notNull(),
  ...timestamps,
});
