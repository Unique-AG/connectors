import { sql } from 'drizzle-orm';
import { check, foreignKey, index, jsonb, pgTable, text } from 'drizzle-orm/pg-core';
import { timestamps, typeId } from './columns.js';
import { tasks } from './tasks.table.js';

export const artifacts = pgTable(
  'a2a_artifacts',
  {
    id: typeId('art'),
    taskId: text().notNull(),
    companyId: text().notNull(),
    kind: text().notNull(),
    contentId: text(),
    artifactSnapshot: jsonb().$type<Record<string, unknown>>().notNull(),
    ...timestamps,
  },
  (table) => [
    check('a2a_artifacts_kind', sql`${table.kind} in ('text', 'data', 'file')`),
    foreignKey({
      name: 'a2a_artifacts_company_task_fk',
      columns: [table.companyId, table.taskId],
      foreignColumns: [tasks.companyId, tasks.id],
    }).onDelete('cascade'),
    index('a2a_artifacts_task_idx').on(table.companyId, table.taskId),
  ],
);
