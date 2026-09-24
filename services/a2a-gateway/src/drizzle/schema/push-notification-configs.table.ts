import { sql } from 'drizzle-orm';
import { check, foreignKey, index, integer, pgTable, text, timestamp, unique } from 'drizzle-orm/pg-core';
import { bytea, timestamps, typeId } from './columns.js';
import { tasks } from './tasks.table.js';

export const pushNotificationConfigs = pgTable(
  'a2a_push_notification_configs',
  {
    id: typeId('pnc'),
    taskId: text().notNull(),
    companyId: text().notNull(),
    url: text().notNull(),
    authCiphertext: bytea(),
    failures: integer().default(0).notNull(),
    disabledAt: timestamp({ withTimezone: true }),
    ...timestamps,
  },
  (table) => [
    unique('a2a_push_configs_task_url_unique').on(table.taskId, table.url),
    foreignKey({
      name: 'a2a_push_configs_company_task_fk',
      columns: [table.companyId, table.taskId],
      foreignColumns: [tasks.companyId, tasks.id],
    }).onDelete('cascade'),
    check('a2a_push_configs_failures_nonnegative', sql`${table.failures} >= 0`),
    index('a2a_push_configs_company_task_idx').on(table.companyId, table.taskId),
  ],
);
