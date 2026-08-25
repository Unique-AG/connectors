import assert from 'node:assert';
import type { CalendarRef } from '../calendar.schemas';
import { SmtpAddressSchema } from './smtp-address.schema';

export const EVENT_RESPONSES = ['accept', 'tentativelyAccept', 'decline'] as const;
export type EventResponse = (typeof EVENT_RESPONSES)[number];

export function calendarCollectionPath(mailboxEmail: string): string {
  return `/users/${mailboxEmail}/calendars`;
}

export function calendarViewPath(input: { calendarId: string; mailboxEmail: string }): string {
  return `/users/${input.mailboxEmail}/calendars/${graphItemIdSegment(input.calendarId, 'calendarId')}/calendarView`;
}

export function getSchedulePath(mailboxEmail: string): string {
  assert.ok(
    SmtpAddressSchema.safeParse(mailboxEmail).success,
    'getSchedule mailbox must be an SMTP address',
  );
  return `/users/${mailboxEmail}/calendar/getSchedule`;
}

export function findMeetingTimesPath(mailboxEmail: string): string {
  assert.ok(
    SmtpAddressSchema.safeParse(mailboxEmail).success,
    'findMeetingTimes mailbox must be an SMTP address',
  );
  return `/users/${mailboxEmail}/findMeetingTimes`;
}

export function calendarMailbox(input: { calendar: CalendarRef; callerEmail: string }): string {
  if (input.calendar.accessPath === 'ownerMailbox') {
    assert.ok(input.calendar.ownerEmail, 'ownerMailbox calendars require ownerEmail');
    return input.calendar.ownerEmail;
  }
  return input.callerEmail;
}

export function defaultCalendarPath(mailboxEmail: string): string {
  assert.ok(
    SmtpAddressSchema.safeParse(mailboxEmail).success,
    'default calendar mailbox must be an SMTP address',
  );
  return `/users/${mailboxEmail}/calendar`;
}

export function createEventPath(input: { mailboxEmail: string; calendarId: string }): string {
  assert.ok(
    SmtpAddressSchema.safeParse(input.mailboxEmail).success,
    'create event mailbox must be an SMTP address',
  );
  return `/users/${input.mailboxEmail}/calendars/${graphItemIdSegment(input.calendarId, 'calendarId')}/events`;
}

export function eventResponsePath(input: {
  mailboxEmail: string;
  calendarId: string;
  eventId: string;
  response: EventResponse;
}): string {
  assert.ok(
    SmtpAddressSchema.safeParse(input.mailboxEmail).success,
    'event response mailbox must be an SMTP address',
  );
  return `/users/${input.mailboxEmail}/calendars/${graphItemIdSegment(input.calendarId, 'calendarId')}/events/${graphItemIdSegment(input.eventId, 'eventId')}/${input.response}`;
}

function graphItemIdSegment(id: string, label: string): string {
  assert.ok(id.length > 0, `${label} must already be set`);
  return encodeURIComponent(id);
}
