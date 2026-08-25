import assert from 'node:assert';
import type { CalendarRef } from './calendar.schemas';

export function calendarViewPath(
  calendar: CalendarRef,
  caller: { source: 'oauth' | 'shared-mailbox'; email: string },
): string {
  if (calendar.accessPath === 'ownerMailbox') {
    assert.ok(calendar.ownerEmail, 'ownerMailbox calendars require ownerEmail');
    return `/users/${calendar.ownerEmail}/calendars/${calendar.calendarId}/calendarView`;
  }
  if (caller.source === 'shared-mailbox') {
    return `/users/${caller.email}/calendars/${calendar.calendarId}/calendarView`;
  }
  return `/me/calendars/${calendar.calendarId}/calendarView`;
}
