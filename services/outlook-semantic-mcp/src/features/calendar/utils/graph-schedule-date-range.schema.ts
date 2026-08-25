import { Temporal } from 'temporal-polyfill';
import * as z from 'zod';
import { DateRangeSchema, type RelativeRange } from '~/utils/relative-range';

export const MAX_GRAPH_SCHEDULE_WINDOW_DAYS = 62;

const RELATIVE_RANGES_LONGER_THAN_62_DAYS = new Set<RelativeRange>([
  'thisYear',
  'nextYear',
  'lastYear',
  'next90Days',
]);

const PAST_ONLY_RELATIVE_RANGES = new Set<RelativeRange>([
  'yesterday',
  'lastWeek',
  'lastMonth',
  'lastYear',
  'past7Days',
  'past30Days',
]);

export function isScheduleWindowTooLong(startDateTime: string, endDateTime: string): boolean {
  const duration = Temporal.Instant.from(startDateTime).until(Temporal.Instant.from(endDateTime));
  return Temporal.Duration.compare(duration, { days: MAX_GRAPH_SCHEDULE_WINDOW_DAYS }) >= 0;
}

function refineScheduleWindow(value: z.infer<typeof DateRangeSchema>, ctx: z.RefinementCtx): void {
  if (value.rangeType === 'relative') {
    if (RELATIVE_RANGES_LONGER_THAN_62_DAYS.has(value.range)) {
      ctx.addIssue({
        code: 'custom',
        message: `Window must be shorter than ${MAX_GRAPH_SCHEDULE_WINDOW_DAYS} days. Use today, thisWeek, nextWeek, or next7Days.`,
        path: ['range'],
      });
    }
    return;
  }
  try {
    if (isScheduleWindowTooLong(value.startDateTime, value.endDateTime)) {
      ctx.addIssue({
        code: 'custom',
        message: `Window must be shorter than ${MAX_GRAPH_SCHEDULE_WINDOW_DAYS} days.`,
        path: ['endDateTime'],
      });
    }
  } catch {
    // DateRangeSchema only requires a Z / ±HH:MM suffix, so Instant.from can still
    // throw (e.g. "not-a-date+02:00"). Swallow so Zod does not surface a Temporal
    // RangeError. The 62-day check is skipped; we do not add a parse issue here.
  }
}

export const GraphScheduleDateRangeSchema = DateRangeSchema.superRefine(refineScheduleWindow);

export const SuggestMeetingDateRangeSchema = DateRangeSchema.superRefine((value, ctx) => {
  refineScheduleWindow(value, ctx);
  if (value.rangeType === 'relative' && PAST_ONLY_RELATIVE_RANGES.has(value.range)) {
    ctx.addIssue({
      code: 'custom',
      message:
        'The window must not be entirely in the past. Use today, tomorrow, thisWeek, or next7Days.',
      path: ['range'],
    });
  }
});
