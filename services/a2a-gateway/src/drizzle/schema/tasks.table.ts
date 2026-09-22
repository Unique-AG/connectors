import { sql } from 'drizzle-orm';
import { foreignKey, index, jsonb, pgTable, text, timestamp, unique, uniqueIndex } from 'drizzle-orm/pg-core';
import { timestamps, typeId } from './columns.js';
import { contexts } from './contexts.table.js';

export const tasks = pgTable(
  'a2a_tasks',
  {
    id: typeId('task'),
    companyId: text().notNull(),
    userId: text().notNull(),
    clientId: text().notNull(),
    contextId: text().notNull(),
    state: text().notNull(),
    userMessageId: text().notNull(),
    assistantMessageId: text(),
    elicitationId: text(),
    taskSnapshot: jsonb().$type<Record<string, unknown>>().notNull(),
    statusTimestamp: timestamp({ withTimezone: true }).defaultNow().notNull(),
    expiresAt: timestamp({ withTimezone: true }).notNull(),
    ...timestamps,
  },
  (table) => [
    unique('a2a_tasks_company_id_unique').on(table.companyId, table.id),
    unique('a2a_tasks_company_user_message_unique').on(table.companyId, table.userMessageId),
    foreignKey({
      name: 'a2a_tasks_company_context_fk',
      columns: [table.companyId, table.contextId],
      foreignColumns: [contexts.companyId, contexts.id],
    }).onDelete('cascade'),
    uniqueIndex('a2a_tasks_one_active_per_context_unique')
      .on(table.contextId)
      .where(sql`${table.state} not in ('3', '4', '5', '7')`),
    index('a2a_tasks_owner_status_idx').on(
      table.companyId,
      table.userId,
      table.statusTimestamp,
      table.id,
    ),
    index('a2a_tasks_expiry_idx').on(table.expiresAt),
  ],
);
