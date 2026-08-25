import type { CalendarRef, EventRef, GraphEvent } from '../calendar.schemas';
import { calendarMailbox } from './calendar-graph-path';
import { summariseRecurrence } from './summarise-recurrence';

const BODY_MAX_CHARS = 4000;

interface CalendarEventAttendee {
  name: string | null;
  email: string | null;
  response: string | null;
  type: string | null;
}

interface CalendarEventDateTime {
  dateTime: string;
  timeZone: string | null;
}

export interface CalendarEvent {
  subject: string | null;
  body: string;
  bodyTruncated: boolean;
  start: CalendarEventDateTime;
  end: CalendarEventDateTime;
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
  eventRef: EventRef;
}

export function mapGraphEventToCalendarEvent(input: {
  event: GraphEvent;
  calendar: CalendarRef;
  callerEmail: string;
}): CalendarEvent {
  const rawBody = input.event.body?.content ?? '';
  const bodyTruncated = rawBody.length > BODY_MAX_CHARS;
  return {
    subject: input.event.subject ?? null,
    body: bodyTruncated ? rawBody.slice(0, BODY_MAX_CHARS) : rawBody,
    bodyTruncated,
    start: {
      dateTime: input.event.start?.dateTime ?? '',
      timeZone: input.event.start?.timeZone ?? null,
    },
    end: {
      dateTime: input.event.end?.dateTime ?? '',
      timeZone: input.event.end?.timeZone ?? null,
    },
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
    eventRef: {
      eventId: input.event.id,
      calendarId: input.calendar.calendarId,
      accessPath: input.calendar.accessPath,
      mailbox: calendarMailbox({
        calendar: input.calendar,
        callerEmail: input.callerEmail,
      }),
    },
  };
}
