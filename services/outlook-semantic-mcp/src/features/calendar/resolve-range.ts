import type { RelativeRange } from './relative-range';

export interface ResolvedWindow {
  startDateTime: string;
  endDateTime: string;
  timeZone: string;
  serverCurrentDateTime: string;
  interpretation: string;
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;

const RANGE_LABEL: Record<RelativeRange, string> = {
  today: 'today',
  tomorrow: 'tomorrow',
  yesterday: 'yesterday',
  thisWeek: 'this week',
  nextWeek: 'next week',
  lastWeek: 'last week',
  thisMonth: 'this month',
  nextMonth: 'next month',
  lastMonth: 'last month',
  thisYear: 'this year',
  nextYear: 'next year',
  lastYear: 'last year',
  next7Days: 'next 7 days',
  next30Days: 'next 30 days',
  next90Days: 'next 90 days',
  past7Days: 'past 7 days',
  past30Days: 'past 30 days',
};

function toGraphInstant(value: Temporal.ZonedDateTime): string {
  return value.toString({ smallestUnit: 'millisecond', timeZoneName: 'never' });
}

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

function formatBoundary(value: Temporal.ZonedDateTime): string {
  const weekday = WEEKDAYS[value.dayOfWeek - 1];
  return `${weekday} ${value.year}-${pad(value.month)}-${pad(value.day)} ${pad(value.hour)}:${pad(value.minute)}`;
}

function startOfIsoWeek(now: Temporal.ZonedDateTime): Temporal.ZonedDateTime {
  return now.startOfDay().subtract({ days: now.dayOfWeek - 1 });
}

function endOfDay(start: Temporal.ZonedDateTime): Temporal.ZonedDateTime {
  return start.add({ days: 1 }).subtract({ milliseconds: 1 });
}

function calendarDay(
  now: Temporal.ZonedDateTime,
  dayOffset: number,
): {
  start: Temporal.ZonedDateTime;
  end: Temporal.ZonedDateTime;
} {
  const start = now.startOfDay().add({ days: dayOffset });
  return { start, end: endOfDay(start) };
}

function boundsFor(
  range: RelativeRange,
  now: Temporal.ZonedDateTime,
): {
  start: Temporal.ZonedDateTime;
  end: Temporal.ZonedDateTime;
} {
  switch (range) {
    case 'today':
      return calendarDay(now, 0);
    case 'tomorrow':
      return calendarDay(now, 1);
    case 'yesterday':
      return calendarDay(now, -1);
    case 'thisWeek': {
      const start = startOfIsoWeek(now);
      return { start, end: endOfDay(start.add({ days: 6 })) };
    }
    case 'nextWeek': {
      const start = startOfIsoWeek(now).add({ weeks: 1 });
      return { start, end: endOfDay(start.add({ days: 6 })) };
    }
    case 'lastWeek': {
      const start = startOfIsoWeek(now).subtract({ weeks: 1 });
      return { start, end: endOfDay(start.add({ days: 6 })) };
    }
    case 'thisMonth': {
      const start = now.with({ day: 1 }).startOfDay();
      return { start, end: start.add({ months: 1 }).subtract({ milliseconds: 1 }) };
    }
    case 'nextMonth': {
      const start = now.with({ day: 1 }).startOfDay().add({ months: 1 });
      return { start, end: start.add({ months: 1 }).subtract({ milliseconds: 1 }) };
    }
    case 'lastMonth': {
      const start = now.with({ day: 1 }).startOfDay().subtract({ months: 1 });
      return { start, end: start.add({ months: 1 }).subtract({ milliseconds: 1 }) };
    }
    case 'thisYear': {
      const start = now.with({ month: 1, day: 1 }).startOfDay();
      return { start, end: start.add({ years: 1 }).subtract({ milliseconds: 1 }) };
    }
    case 'nextYear': {
      const start = now.with({ month: 1, day: 1 }).startOfDay().add({ years: 1 });
      return { start, end: start.add({ years: 1 }).subtract({ milliseconds: 1 }) };
    }
    case 'lastYear': {
      const start = now.with({ month: 1, day: 1 }).startOfDay().subtract({ years: 1 });
      return { start, end: start.add({ years: 1 }).subtract({ milliseconds: 1 }) };
    }
    case 'next7Days':
      return { start: now, end: now.add({ days: 7 }) };
    case 'next30Days':
      return { start: now, end: now.add({ days: 30 }) };
    case 'next90Days':
      return { start: now, end: now.add({ days: 90 }) };
    case 'past7Days':
      return { start: now.subtract({ days: 7 }), end: now };
    case 'past30Days':
      return { start: now.subtract({ days: 30 }), end: now };
  }
}

export function resolveRange(
  range: RelativeRange,
  timeZone: string,
  now: Temporal.ZonedDateTime,
): ResolvedWindow {
  const { start, end } = boundsFor(range, now);
  return {
    startDateTime: toGraphInstant(start),
    endDateTime: toGraphInstant(end),
    timeZone,
    serverCurrentDateTime: toGraphInstant(now),
    interpretation: `${RANGE_LABEL[range]} = ${formatBoundary(start)} to ${formatBoundary(end)} (${timeZone})`,
  };
}
