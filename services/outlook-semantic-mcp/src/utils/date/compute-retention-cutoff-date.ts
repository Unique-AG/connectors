import { startOfUtcDay } from './start-of-utc-day';
import { subDays } from './sub-days';

export function computeRetentionCutoffDate(days: number): Date {
  return startOfUtcDay(subDays(new Date(), days));
}
