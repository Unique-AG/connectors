import { jsonb, pgTable, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '~/db/timestamps.columns';
import { CacheData } from './cache.data';

export const caches = pgTable('caches', {
  key: varchar()
    .primaryKey()
    .$default(() => typeid('cache').toString()),
  data: jsonb(`filters`).$type<CacheData>().notNull(),
  ...timestamps,
});
