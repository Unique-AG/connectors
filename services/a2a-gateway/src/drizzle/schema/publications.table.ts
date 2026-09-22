import { sql } from 'drizzle-orm';
import { boolean, check, index, integer, jsonb, pgTable, text, timestamp, unique } from 'drizzle-orm/pg-core';
import { timestamps, typeId } from './columns.js';

export const publications = pgTable(
  'a2a_publications',
  {
    id: typeId('pub'),
    companyId: text().notNull(),
    assistantId: text().notNull(),
    enabled: boolean().default(true).notNull(),
    cardOverrides: jsonb().$type<Record<string, unknown>>().default({}).notNull(),
    skills: jsonb().$type<unknown[]>().default([]).notNull(),
    version: integer().default(1).notNull(),
    createdByUserId: text().notNull(),
    disabledAt: timestamp({ withTimezone: true }),
    ...timestamps,
  },
  (table) => [
    unique('a2a_publications_company_id_unique').on(table.companyId, table.id),
    unique('a2a_publications_company_assistant_unique').on(table.companyId, table.assistantId),
    check('a2a_publications_version_positive', sql`${table.version} > 0`),
    index('a2a_publications_company_enabled_idx').on(table.companyId, table.enabled),
  ],
);
