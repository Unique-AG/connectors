import { startOfUtcDay } from './start-of-utc-day';
import { subUtcDays } from './sub-utc-days';

export const computeRetentionCutoffDate = (days: number): Date => {
  return startOfUtcDay(subUtcDays(new Date(), days));
};
