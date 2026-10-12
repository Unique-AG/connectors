import { index, jsonb, pgTable, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';

// Pagination positions handed to the agent as opaque ids by `search_emails` and
// `fetch_next_search_pages`. Rows are immutable: each row is one page position.
export const searchCursors = pgTable(
  'search_cursors',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('search_cursor').toString()),
    // Validated against SearchCursorPayloadSchema on read.
    payload: jsonb('payload').$type<unknown>().notNull(),

    // References
    userProfileId: varchar('user_profile_id')
      .notNull()
      .references(() => userProfiles.id, {
        onDelete: 'cascade',
        onUpdate: 'cascade',
      }),

    ...timestamps,
  },
  (table) => [index().on(table.createdAt)],
);

export type SearchCursor = typeof searchCursors.$inferSelect;
