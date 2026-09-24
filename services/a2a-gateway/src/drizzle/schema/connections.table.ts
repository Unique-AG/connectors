import { sql } from 'drizzle-orm';
import { check, index, integer, jsonb, pgTable, text, timestamp, unique } from 'drizzle-orm/pg-core';
import { bytea, timestamps, typeId } from './columns.js';

export const connections = pgTable(
  'a2a_connections',
  {
    id: typeId('conn'),
    companyId: text().notNull(),
    name: text().notNull(),
    agentCardUrl: text().notNull(),
    agentCardSnapshot: jsonb().$type<Record<string, unknown>>(),
    negotiatedCapabilities: jsonb().$type<Record<string, unknown>>().default({}).notNull(),
    credentialType: text(),
    credentialCiphertext: bytea(),
    version: integer().default(1).notNull(),
    lastVerifiedAt: timestamp({ withTimezone: true }),
    lastError: text(),
    disabledAt: timestamp({ withTimezone: true }),
    ...timestamps,
  },
  (table) => [
    unique('a2a_connections_company_id_unique').on(table.companyId, table.id),
    unique('a2a_connections_company_name_unique').on(table.companyId, table.name),
    check('a2a_connections_version_positive', sql`${table.version} > 0`),
    index('a2a_connections_company_idx').on(table.companyId),
  ],
);
