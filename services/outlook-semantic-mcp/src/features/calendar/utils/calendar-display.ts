import { Temporal } from 'temporal-polyfill';
import { resolveIanaTimezone } from '~/utils/resolve-iana-timezone';
import type { CalendarDateTime } from './map-graph-date-time';

/** Collapses whitespace so a pasted multi-line subject cannot reflow an elicitation prompt. */
export function oneLine(value: string): string {
  return value.replaceAll(/\s+/g, ' ').trim();
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;
const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const;

export type DisplayDateTime = CalendarDateTime | string;

/**
 * Elicitation is shown to the user, not the model. MCP does not give us a locale, so this is one
 * default: weekday, day month year, 24-hour time, GMT offset. Graph's 7-digit ISO is never shown.
 */
export function formatDisplayWhen(
  start: DisplayDateTime | null | undefined,
  end?: DisplayDateTime | null,
): string | undefined {
  if (start === null || start === undefined) {
    return undefined;
  }
  const startZoned = toZoned(start);
  const endZoned = end === null || end === undefined ? undefined : toZoned(end);
  if (startZoned !== undefined && endZoned !== undefined) {
    return formatZonedRange(startZoned, endZoned);
  }
  if (startZoned !== undefined) {
    return formatZoned(startZoned);
  }
  const startText = formatFallback(start);
  if (end === null || end === undefined) {
    return startText;
  }
  const endText = endZoned !== undefined ? formatZoned(endZoned) : formatFallback(end);
  return startText === endText ? startText : `${startText} – ${endText}`;
}

function formatZonedRange(start: Temporal.ZonedDateTime, end: Temporal.ZonedDateTime): string {
  const sameDay =
    start.toPlainDate().equals(end.toPlainDate()) && start.timeZoneId === end.timeZoneId;
  if (sameDay) {
    return `${formatDate(start)}, ${formatTime(start)}–${formatTime(end)} ${formatGmtOffset(start)}`;
  }
  if (start.offset === end.offset) {
    return `${formatDate(start)}, ${formatTime(start)} – ${formatDate(end)}, ${formatTime(end)} ${formatGmtOffset(start)}`;
  }
  return `${formatZoned(start)} – ${formatZoned(end)}`;
}

function formatZoned(value: Temporal.ZonedDateTime): string {
  return `${formatDate(value)}, ${formatTime(value)} ${formatGmtOffset(value)}`;
}

function formatDate(value: Temporal.ZonedDateTime): string {
  return `${WEEKDAYS[value.dayOfWeek - 1]} ${value.day} ${MONTHS[value.month - 1]} ${value.year}`;
}

function formatTime(value: Temporal.ZonedDateTime): string {
  return `${pad(value.hour)}:${pad(value.minute)}`;
}

function formatGmtOffset(value: Temporal.ZonedDateTime): string {
  const offset = value.offset;
  const sign = offset.startsWith('-') ? '-' : '+';
  const hours = Number(offset.slice(1, 3));
  const minutes = offset.slice(4, 6);
  if (hours === 0 && minutes === '00') {
    return 'GMT';
  }
  return minutes === '00' ? `GMT${sign}${hours}` : `GMT${sign}${hours}:${minutes}`;
}

function toZoned(value: DisplayDateTime): Temporal.ZonedDateTime | undefined {
  return typeof value === 'string' ? parseOffsetInstant(value) : parseGraphDateTime(value);
}

function parseOffsetInstant(iso: string): Temporal.ZonedDateTime | undefined {
  try {
    const instant = Temporal.Instant.from(iso);
    const match = iso.match(/([+-]\d{2}:\d{2}|Z)$/i);
    const timeZone = match === null || match[1]?.toUpperCase() === 'Z' ? 'UTC' : match[1];
    return instant.toZonedDateTimeISO(timeZone ?? 'UTC');
  } catch {
    return undefined;
  }
}

function parseGraphDateTime(value: CalendarDateTime): Temporal.ZonedDateTime | undefined {
  if (/(?:Z|[+-]\d{2}:\d{2})$/i.test(value.dateTime)) {
    return parseOffsetInstant(value.dateTime);
  }
  const plain = parsePlainDateTime(value.dateTime);
  if (plain === undefined) {
    return undefined;
  }
  const iana =
    value.timeZone !== null && value.timeZone !== ''
      ? resolveIanaTimezone(value.timeZone)
      : undefined;
  if (iana === undefined) {
    return undefined;
  }
  try {
    return plain.toZonedDateTime(iana);
  } catch {
    return undefined;
  }
}

function parsePlainDateTime(dateTime: string): Temporal.PlainDateTime | undefined {
  try {
    return Temporal.PlainDateTime.from(dateTime);
  } catch {
    try {
      return Temporal.PlainDateTime.from(
        dateTime.replace(/\.\d+/, (fraction) => fraction.slice(0, 4)),
      );
    } catch {
      return undefined;
    }
  }
}

function formatFallback(value: DisplayDateTime): string {
  if (typeof value === 'string') {
    return value;
  }
  const plain = parsePlainDateTime(value.dateTime);
  if (plain === undefined) {
    return value.dateTime;
  }
  const weekday = WEEKDAYS[plain.dayOfWeek - 1];
  const month = MONTHS[plain.month - 1];
  return `${weekday} ${plain.day} ${month} ${plain.year}, ${pad(plain.hour)}:${pad(plain.minute)}`;
}

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

export interface CalendarDisplay {
  name: string;
  isDefaultCalendar: boolean;
  isOwn: boolean;
  ownerEmail: string | null;
  ownerName: string | null;
}

/**
 * Names the calendar the way the user recognises it, by owner rather than by which account it is
 * stored under: a calendar shared with the signed-in user is stored under their own account, so
 * saying so would read as if the event were landing on their personal calendar.
 */
export function describeCalendar(calendar: CalendarDisplay): string {
  const name = oneLine(calendar.name) === '' ? 'Calendar' : oneLine(calendar.name);
  if (calendar.isOwn) {
    return calendar.isDefaultCalendar
      ? `"${name}" — your primary calendar`
      : `"${name}" — your calendar`;
  }
  const owner =
    calendar.ownerName !== null && calendar.ownerEmail !== null
      ? `${oneLine(calendar.ownerName)} (${calendar.ownerEmail})`
      : (calendar.ownerEmail ?? calendar.ownerName ?? 'another mailbox');
  return calendar.isDefaultCalendar
    ? `"${name}" — the primary calendar of ${owner}`
    : `"${name}" — shared by ${owner}`;
}
