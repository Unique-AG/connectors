import { encodeGraphItemIdForUrlPath } from '~/msgraph/encode-graph-item-id-for-url-path';
import type { CalendarRef, EventRef } from './calendar.schemas';

export function calendarPreferHeader(mailboxTimeZone?: string): string {
  const parts = ['outlook.body-content-type="text"', 'IdType="ImmutableId"'];
  if (mailboxTimeZone) {
    parts.unshift(`outlook.timezone="${mailboxTimeZone}"`);
  }
  return parts.join(', ');
}

export function calendarViewPath(calendar: CalendarRef, sharedMailboxEmail: string | null): string {
  if (sharedMailboxEmail) {
    return `/users/${sharedMailboxEmail}/calendars/${encodeGraphItemIdForUrlPath(calendar.calendarId)}/calendarView`;
  }
  if (calendar.accessPath === 'ownerMailbox' && calendar.ownerEmail) {
    return `/users/${calendar.ownerEmail}/calendar/calendarView`;
  }
  return `/me/calendars/${encodeGraphItemIdForUrlPath(calendar.calendarId)}/calendarView`;
}

export function eventPath(eventRef: EventRef, sharedMailboxEmail: string | null): string {
  const eventId = encodeGraphItemIdForUrlPath(eventRef.eventId);
  if (sharedMailboxEmail) {
    return `/users/${sharedMailboxEmail}/calendars/${encodeGraphItemIdForUrlPath(eventRef.calendarId)}/events/${eventId}`;
  }
  if (eventRef.accessPath === 'ownerMailbox' && eventRef.mailbox) {
    return `/users/${eventRef.mailbox}/events/${eventId}`;
  }
  return `/me/calendars/${encodeGraphItemIdForUrlPath(eventRef.calendarId)}/events/${eventId}`;
}

export function eventsCollectionPath(
  calendar: CalendarRef,
  sharedMailboxEmail: string | null,
): string {
  if (sharedMailboxEmail) {
    return `/users/${sharedMailboxEmail}/calendars/${encodeGraphItemIdForUrlPath(calendar.calendarId)}/events`;
  }
  if (calendar.accessPath === 'ownerMailbox' && calendar.ownerEmail) {
    return `/users/${calendar.ownerEmail}/events`;
  }
  return `/me/calendars/${encodeGraphItemIdForUrlPath(calendar.calendarId)}/events`;
}

export function findMeetingTimesPath(sharedMailboxEmail: string | null): string {
  return sharedMailboxEmail
    ? `/users/${sharedMailboxEmail}/findMeetingTimes`
    : '/me/findMeetingTimes';
}

export function getSchedulePath(sharedMailboxEmail: string | null): string {
  return sharedMailboxEmail
    ? `/users/${sharedMailboxEmail}/calendar/getSchedule`
    : '/me/calendar/getSchedule';
}

export function toEventRef(calendar: CalendarRef, eventId: string): EventRef {
  return {
    eventId,
    calendarId: calendar.calendarId,
    accessPath: calendar.accessPath,
    mailbox: calendar.accessPath === 'ownerMailbox' ? calendar.ownerEmail : null,
  };
}
