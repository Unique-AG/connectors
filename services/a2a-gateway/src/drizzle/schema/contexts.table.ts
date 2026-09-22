import { foreignKey, index, pgTable, text, unique } from 'drizzle-orm/pg-core';
import { timestamps, typeId } from './columns.js';
import { publications } from './publications.table.js';

export const contexts = pgTable(
  'a2a_contexts',
  {
    id: typeId('ctx'),
    companyId: text().notNull(),
    userId: text().notNull(),
    publicationId: text().notNull(),
    chatId: text().notNull(),
    ...timestamps,
  },
  (table) => [
    unique('a2a_contexts_company_id_unique').on(table.companyId, table.id),
    unique('a2a_contexts_company_chat_unique').on(table.companyId, table.chatId),
    foreignKey({
      name: 'a2a_contexts_company_publication_fk',
      columns: [table.companyId, table.publicationId],
      foreignColumns: [publications.companyId, publications.id],
    }).onDelete('restrict'),
    index('a2a_contexts_owner_idx').on(table.companyId, table.userId),
  ],
);
