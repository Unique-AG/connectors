import assert from 'node:assert';

export const EVENT_RESPONSES = ['accept', 'tentativelyAccept', 'decline'] as const;
export type EventResponse = (typeof EVENT_RESPONSES)[number];

/**
 * Every path is rooted at `/me`, which Graph resolves to the signed-in user of the delegated token
 * GraphClientFactory.createClientForUser builds. `/me/X` and `/users/{signed-in user}/X` are the
 * same resource, and calendar and event ids only ever reach us from `/me/calendars` — including
 * shared ones, which Graph stores as a local copy in the recipient's own mailbox. So there is no
 * mailbox to thread through: the token already names it.
 *
 * This holds only for delegated auth. An app-only (client credentials) token has no signed-in user
 * and `/me` fails; that would mean going back to `/users/{id}`.
 */
export function calendarCollectionPath(): string {
  return '/me/calendars';
}

export function calendarViewPath(calendarId: string): string {
  return `/me/calendars/${graphItemIdSegment(calendarId, 'calendarId')}/calendarView`;
}

/**
 * The Graph JS SDK concatenates query values without percent-encoding. In
 * application/x-www-form-urlencoded a `+` is a space, so `…T00:00:00.000+02:00`
 * arrives as `…T00:00:00.000 02:00` and calendarView rejects StartDateTime.
 */
export function encodeGraphQueryInstant(iso: string): string {
  return iso.replaceAll('+', '%2B');
}

export function getSchedulePath(): string {
  return '/me/calendar/getSchedule';
}

export function findMeetingTimesPath(): string {
  return '/me/findMeetingTimes';
}

export function defaultCalendarPath(): string {
  return '/me/calendar';
}

export function calendarPath(calendarId: string): string {
  return `/me/calendars/${graphItemIdSegment(calendarId, 'calendarId')}`;
}

export function createEventPath(calendarId: string): string {
  return `/me/calendars/${graphItemIdSegment(calendarId, 'calendarId')}/events`;
}

export function eventPath(input: { calendarId: string; eventId: string }): string {
  return `/me/calendars/${graphItemIdSegment(input.calendarId, 'calendarId')}/events/${graphItemIdSegment(input.eventId, 'eventId')}`;
}

export function eventResponsePath(input: {
  calendarId: string;
  eventId: string;
  response: EventResponse;
}): string {
  return `${eventPath(input)}/${input.response}`;
}

export function eventCancelPath(input: { calendarId: string; eventId: string }): string {
  return `${eventPath(input)}/cancel`;
}

function graphItemIdSegment(id: string, label: string): string {
  assert.ok(id.length > 0, `${label} must already be set`);
  return encodeURIComponent(id);
}
