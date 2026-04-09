import { SQL, sql } from 'drizzle-orm';
import { PgColumn } from 'drizzle-orm/pg-core';

export const greatestFrom = (columnRef: PgColumn, date: Date): SQL<unknown> => {
  return sql`GREATEST(COALESCE(${columnRef}, '-infinity'::timestamptz), ${date})`;
};
