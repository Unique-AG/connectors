import { foreignKey, index, jsonb, pgTable, text, timestamp, unique } from 'drizzle-orm/pg-core';
import { timestamps, typeId } from './columns.js';
import { connections } from './connections.table.js';

export const executions = pgTable(
  'a2a_executions',
  {
    id: typeId('exec'),
    companyId: text().notNull(),
    userId: text().notNull(),
    connectionId: text().notNull(),
    assistantId: text().notNull(),
    chatId: text().notNull(),
    userMessageId: text().notNull(),
    assistantMessageId: text().notNull(),
    remoteTaskId: text(),
    state: text().notNull(),
    correlation: jsonb().$type<Record<string, unknown>>().default({}).notNull(),
    elicitationId: text(),
    deadlineAt: timestamp({ withTimezone: true }),
    lastError: text(),
    expiresAt: timestamp({ withTimezone: true }).notNull(),
    ...timestamps,
  },
  (table) => [
    unique('a2a_executions_company_user_message_unique').on(table.companyId, table.userMessageId),
    foreignKey({
      name: 'a2a_executions_company_connection_fk',
      columns: [table.companyId, table.connectionId],
      foreignColumns: [connections.companyId, connections.id],
    }).onDelete('restrict'),
    index('a2a_executions_recovery_idx').on(table.companyId, table.state, table.updatedAt),
    index('a2a_executions_expiry_idx').on(table.expiresAt),
  ],
);
