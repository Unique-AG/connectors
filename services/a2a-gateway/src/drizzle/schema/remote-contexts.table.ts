import { foreignKey, pgTable, text, unique } from 'drizzle-orm/pg-core';
import { timestamps, typeId } from './columns.js';
import { connections } from './connections.table.js';

export const remoteContexts = pgTable(
  'a2a_remote_contexts',
  {
    id: typeId('rctx'),
    companyId: text().notNull(),
    connectionId: text().notNull(),
    chatId: text().notNull(),
    remoteContextId: text().notNull(),
    ...timestamps,
  },
  (table) => [
    unique('a2a_remote_contexts_company_chat_unique').on(table.companyId, table.chatId),
    foreignKey({
      name: 'a2a_remote_contexts_company_connection_fk',
      columns: [table.companyId, table.connectionId],
      foreignColumns: [connections.companyId, connections.id],
    }).onDelete('cascade'),
    unique('a2a_remote_contexts_connection_remote_unique').on(
      table.companyId,
      table.connectionId,
      table.remoteContextId,
    ),
  ],
);
