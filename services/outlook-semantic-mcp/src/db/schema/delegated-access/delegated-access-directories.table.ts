import { relations } from 'drizzle-orm';
import { pgTable, text, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { delegatedAccessAccounts } from './delegated-access-accounts.table';

export const delegatedAccessDirectories = pgTable(
  'delegated_access_directories',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('dad').toString()),
    accountsId: varchar(`accounts_id`)
      .notNull()
      .references(() => delegatedAccessAccounts.id, {
        onDelete: 'cascade',
        onUpdate: 'cascade',
      }),
    // We do not make a foreign key out of this directory because the delegated access sync and the emails / directories sync
    // process should be decoupled and if we discover a new directory in a user inbox during delegate access sync we should be
    // able to add that directory id to our search.
    directoryId: text(`directory_id`).notNull(),

    ...timestamps,
  },
  (t) => [unique('unique_accounts_directory').on(t.accountsId, t.directoryId)],
);

export const delegatedAccessDirectoriesRelations = relations(
  delegatedAccessDirectories,
  ({ one }) => ({
    accounts: one(delegatedAccessAccounts, {
      fields: [delegatedAccessDirectories.accountsId],
      references: [delegatedAccessAccounts.id],
    }),
  }),
);

export type DelegatedAccessDirectory = typeof delegatedAccessDirectories.$inferSelect;
