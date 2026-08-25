import assert from 'node:assert';
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

export function defaultCalendarPath(mailboxEmail: string): string {
  assert.ok(
    SmtpAddressSchema.safeParse(mailboxEmail).success,
    'default calendar mailbox must be an SMTP address',
  );
  return `/users/${mailboxEmail}/calendar`;
}

export function calendarPath(input: { mailboxEmail: string; calendarId: string }): string {
  assert.ok(
    SmtpAddressSchema.safeParse(input.mailboxEmail).success,
    'calendar mailbox must be an SMTP address',
  );
  return `/users/${input.mailboxEmail}/calendars/${graphItemIdSegment(input.calendarId, 'calendarId')}`;
}

export function createEventPath(input: { mailboxEmail: string; calendarId: string }): string {
  assert.ok(
    SmtpAddressSchema.safeParse(input.mailboxEmail).success,
    'create event mailbox must be an SMTP address',
  );
  return `/users/${input.mailboxEmail}/calendars/${graphItemIdSegment(input.calendarId, 'calendarId')}/events`;
}

export function eventPath(input: {
  mailboxEmail: string;
  calendarId: string;
  eventId: string;
}): string {
  assert.ok(
    SmtpAddressSchema.safeParse(input.mailboxEmail).success,
    'event mailbox must be an SMTP address',
  );
  return `/users/${input.mailboxEmail}/calendars/${graphItemIdSegment(input.calendarId, 'calendarId')}/events/${graphItemIdSegment(input.eventId, 'eventId')}`;
}

export function eventResponsePath(input: {
  mailboxEmail: string;
  calendarId: string;
  eventId: string;
  response: EventResponse;
}): string {
  return `${eventPath(input)}/${input.response}`;
}

export function eventCancelPath(input: {
  mailboxEmail: string;
  calendarId: string;
  eventId: string;
}): string {
  return `${eventPath(input)}/cancel`;
}

function graphItemIdSegment(id: string, label: string): string {
  assert.ok(id.length > 0, `${label} must already be set`);
  return encodeURIComponent(id);
}
