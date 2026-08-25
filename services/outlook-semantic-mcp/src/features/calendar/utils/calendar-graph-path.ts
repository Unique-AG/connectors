import assert from 'node:assert';
import type { CalendarRef } from '../calendar.schemas';
import { SmtpAddressSchema } from './smtp-address.schema';

export function calendarCollectionPath(mailboxEmail: string): string {
  return `/users/${mailboxEmail}/calendars`;
}

export function calendarViewPath(input: { calendarId: string; mailboxEmail: string }): string {
  return `/users/${input.mailboxEmail}/calendars/${input.calendarId}/calendarView`;
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
