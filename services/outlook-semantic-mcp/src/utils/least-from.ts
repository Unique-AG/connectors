import { SQL, sql } from 'drizzle-orm';
import { PgColumn } from 'drizzle-orm/pg-core';

export const leastFrom = (columnRef: PgColumn, date: Date): SQL<unknown> => {
  return sql`LEAST(COALESCE(${columnRef}, '+infinity'::timestamptz), ${date})`;
};
