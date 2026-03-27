import { SQL, sql } from 'drizzle-orm';

export const getThreshold = (thresholdInMinutes: number): SQL<unknown> => {
  return sql`NOW() - (${thresholdInMinutes} * INTERVAL '1 minute')`;
};
