import type { RelativeRange } from '~/utils/relative-range';

const DAY_MS = 24 * 60 * 60 * 1000;

const DATE_WINDOW_LIMITS = [
  { label: '<1week', maxMs: 7 * DAY_MS },
  { label: '<1month', maxMs: 31 * DAY_MS },
  { label: '<3months', maxMs: 92 * DAY_MS },
  { label: '<6months', maxMs: 183 * DAY_MS },
  { label: '<9months', maxMs: 275 * DAY_MS },
  { label: '<1year', maxMs: 366 * DAY_MS },
  { label: '<2years', maxMs: 731 * DAY_MS },
] as const;

export type DateWindowBucket = (typeof DATE_WINDOW_LIMITS)[number]['label'] | '>2years' | 'unknown';

const RELATIVE_RANGE_DATE_WINDOW: Record<RelativeRange, DateWindowBucket> = {
  today: '<1week',
  tomorrow: '<1week',
  yesterday: '<1week',
  thisWeek: '<1week',
  nextWeek: '<1week',
  lastWeek: '<1week',
  next7Days: '<1week',
  past7Days: '<1week',
  thisMonth: '<1month',
  nextMonth: '<1month',
  lastMonth: '<1month',
  next30Days: '<1month',
  past30Days: '<1month',
  next90Days: '<3months',
  thisYear: '<1year',
  nextYear: '<1year',
  lastYear: '<1year',
};

export function dateWindowBucket(startDateTime: string, endDateTime: string): DateWindowBucket {
  const start = Date.parse(startDateTime);
  const end = Date.parse(endDateTime);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) {
    return 'unknown';
  }
  const durationMs = end - start;
  for (const limit of DATE_WINDOW_LIMITS) {
    if (durationMs <= limit.maxMs) {
      return limit.label;
    }
  }
  return '>2years';
}

export function dateWindowFromSearchInput(input: {
  range?: RelativeRange;
  startDateTime?: string;
  endDateTime?: string;
}): DateWindowBucket {
  if (input.range !== undefined) {
    return RELATIVE_RANGE_DATE_WINDOW[input.range];
  }
  if (input.startDateTime !== undefined && input.endDateTime !== undefined) {
    return dateWindowBucket(input.startDateTime, input.endDateTime);
  }
  return 'unknown';
}
