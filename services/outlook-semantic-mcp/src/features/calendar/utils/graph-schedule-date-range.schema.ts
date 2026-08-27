import { Temporal } from 'temporal-polyfill';
import * as z from 'zod';
import { DateRangeSchema, type RelativeRange } from '~/utils/relative-range';

export const MAX_GRAPH_SCHEDULE_WINDOW_DAYS = 62;
/** Microsoft Graph `getSchedule` `schedules` array size. */
export const MAX_GRAPH_SCHEDULE_ADDRESSES = 20;

// Record rather than Set so the compiler forces a decision when a RelativeRange is added.
const RELATIVE_RANGE_EXCEEDS_62_DAYS: Record<RelativeRange, boolean> = {
  today: false,
  tomorrow: false,
  yesterday: false,
  thisWeek: false,
  nextWeek: false,
  lastWeek: false,
  thisMonth: false,
  nextMonth: false,
  lastMonth: false,
  thisYear: true,
  nextYear: true,
  lastYear: true,
  next7Days: false,
  next30Days: false,
  next90Days: true,
  past7Days: false,
  past30Days: false,
};

const RELATIVE_RANGE_IS_PAST_ONLY: Record<RelativeRange, boolean> = {
  today: false,
  tomorrow: false,
  yesterday: true,
  thisWeek: false,
  nextWeek: false,
  lastWeek: true,
  thisMonth: false,
  nextMonth: false,
  lastMonth: true,
  thisYear: false,
  nextYear: false,
  lastYear: true,
  next7Days: false,
  next30Days: false,
  next90Days: false,
  past7Days: true,
  past30Days: true,
};

export function isScheduleWindowTooLong(startDateTime: string, endDateTime: string): boolean {
  const duration = Temporal.Instant.from(startDateTime).until(Temporal.Instant.from(endDateTime));
  return Temporal.Duration.compare(duration, { days: MAX_GRAPH_SCHEDULE_WINDOW_DAYS }) >= 0;
}

function refineScheduleWindow(value: z.infer<typeof DateRangeSchema>, ctx: z.RefinementCtx): void {
  if (value.rangeType === 'relative') {
    if (RELATIVE_RANGE_EXCEEDS_62_DAYS[value.range]) {
      ctx.addIssue({
        code: 'custom',
        message: `Window must be shorter than ${MAX_GRAPH_SCHEDULE_WINDOW_DAYS} days. Use today, thisWeek, nextWeek, or next7Days.`,
        path: ['range'],
      });
    }
    return;
  }
  if (!isValidInstant(value.startDateTime) || !isValidInstant(value.endDateTime)) {
    return;
  }
  if (isScheduleWindowTooLong(value.startDateTime, value.endDateTime)) {
    ctx.addIssue({
      code: 'custom',
      message: `Window must be shorter than ${MAX_GRAPH_SCHEDULE_WINDOW_DAYS} days.`,
      path: ['endDateTime'],
    });
  }
}

function isValidInstant(value: string): boolean {
  try {
    Temporal.Instant.from(value);
    return true;
  } catch {
    return false;
  }
}

export const GraphScheduleDateRangeSchema = DateRangeSchema.superRefine(refineScheduleWindow);

export const SuggestMeetingDateRangeSchema = DateRangeSchema.superRefine((value, ctx) => {
  refineScheduleWindow(value, ctx);
  if (value.rangeType === 'relative' && RELATIVE_RANGE_IS_PAST_ONLY[value.range]) {
    ctx.addIssue({
      code: 'custom',
      message:
        'The window must not be entirely in the past. Use today, tomorrow, thisWeek, or next7Days.',
      path: ['range'],
    });
  }
});
