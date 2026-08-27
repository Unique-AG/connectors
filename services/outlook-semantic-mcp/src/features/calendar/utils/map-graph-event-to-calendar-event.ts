import type { CalendarRef, EventRef, GraphEvent } from '../calendar.schemas';
import { type CalendarDateTime, mapGraphDateTime } from './map-graph-date-time';
import { summariseRecurrence } from './summarise-recurrence';

const BODY_MAX_CHARS = 4000;
/** A search result is always shaped as a time range, so a missing boundary still needs both keys. */
const UNKNOWN_DATE_TIME: CalendarDateTime = { dateTime: '', timeZone: null };

interface CalendarEventAttendee {
  name: string | null;
  email: string | null;
  response: string | null;
  type: string | null;
}

export interface CalendarEvent {
  subject: string | null;
  body: string;
  bodyTruncated: boolean;
  start: CalendarDateTime;
  end: CalendarDateTime;
  location: string | null;
  joinUrl: string | null;
  attendees: CalendarEventAttendee[];
  organizerName: string | null;
  organizerEmail: string | null;
  isCancelled: boolean;
  isAllDay: boolean;
  isPrivate: boolean;
  sensitivity: string | null;
  categories: string[];
  recurrence: string | null;
  seriesMasterId: string | null;
  type: string | null;
  showAs: string | null;
  webLink: string | null;
  calendarName: string;
  ownerEmail: string | null;
  ownerName: string | null;
  isOwn: boolean;
  eventRef: EventRef;
}

export function mapGraphEventToCalendarEvent(input: {
  event: GraphEvent;
  calendar: CalendarRef;
}): CalendarEvent {
  const rawBody = input.event.body?.content ?? '';
  const bodyTruncated = rawBody.length > BODY_MAX_CHARS;
  return {
    subject: input.event.subject ?? null,
    body: bodyTruncated ? rawBody.slice(0, BODY_MAX_CHARS) : rawBody,
    bodyTruncated,
    start: mapGraphDateTime(input.event.start) ?? UNKNOWN_DATE_TIME,
    end: mapGraphDateTime(input.event.end) ?? UNKNOWN_DATE_TIME,
    location: input.event.location?.displayName ?? null,
    joinUrl: input.event.onlineMeeting?.joinUrl ?? input.event.onlineMeetingUrl ?? null,
    attendees: (input.event.attendees ?? []).map((attendee) => ({
      name: attendee.emailAddress?.name ?? null,
      email: attendee.emailAddress?.address ?? null,
      response: attendee.status?.response ?? null,
      type: attendee.type ?? null,
    })),
    organizerName: input.event.organizer?.emailAddress?.name ?? null,
    organizerEmail: input.event.organizer?.emailAddress?.address ?? null,
    isCancelled: input.event.isCancelled ?? false,
    isAllDay: input.event.isAllDay ?? false,
    isPrivate: input.event.sensitivity === 'private' || input.event.sensitivity === 'confidential',
    sensitivity: input.event.sensitivity ?? null,
    categories: input.event.categories ?? [],
    recurrence: summariseRecurrence(input.event.recurrence?.pattern),
    seriesMasterId: input.event.seriesMasterId ?? null,
    type: input.event.type ?? null,
    showAs: input.event.showAs ?? null,
    webLink: input.event.webLink ?? null,
    calendarName: input.calendar.name,
    ownerEmail: input.calendar.ownerEmail,
    ownerName: input.calendar.ownerName,
    isOwn: input.calendar.isOwn,
    eventRef: {
      eventId: input.event.id,
      calendarId: input.calendar.calendarId,
    },
  };
}
