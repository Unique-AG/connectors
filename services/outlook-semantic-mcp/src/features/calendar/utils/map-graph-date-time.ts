import type { GraphDateTimeTimeZone } from '../calendar.schemas';

export interface CalendarDateTime {
  dateTime: string;
  timeZone: string | null;
}

/**
 * Graph returns a boundary as an optional object with two optional strings. A boundary with no
 * dateTime carries no information, so it collapses to null rather than to an empty string that
 * later reads as a real timestamp.
 */
export function mapGraphDateTime(
  value: GraphDateTimeTimeZone | null | undefined,
): CalendarDateTime | null {
  if (value?.dateTime === undefined || value.dateTime === '') {
    return null;
  }
  return { dateTime: value.dateTime, timeZone: value.timeZone ?? null };
}
