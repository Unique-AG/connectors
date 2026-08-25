import { describe, expect, it } from 'vitest';
import type { CalendarRef } from '../../calendar.schemas';
import {
  calendarCollectionPath,
  calendarMailbox,
  calendarViewPath,
  findMeetingTimesPath,
  getSchedulePath,
} from '../calendar-graph-path';

const own: CalendarRef = {
  calendarId: 'cal-1',
  name: 'Calendar',
  ownerEmail: 'me@example.com',
  ownerName: 'Me',
  isOwn: true,
  canEdit: true,
  canViewPrivateItems: true,
  accessPath: 'ownMailbox',
};

const delegated: CalendarRef = {
  calendarId: 'cal-2',
  name: 'Banker',
  ownerEmail: 'banker@example.com',
  ownerName: 'Banker',
  isOwn: false,
  canEdit: true,
  canViewPrivateItems: false,
  accessPath: 'ownerMailbox',
};

describe(calendarViewPath.name, () => {
  it('always uses /users/{email}/calendars for the caller mailbox', () => {
    expect(calendarViewPath({ calendarId: own.calendarId, mailboxEmail: 'me@example.com' })).toBe(
      '/users/me@example.com/calendars/cal-1/calendarView',
    );
  });

  it('uses the owner mailbox for delegated calendars', () => {
    expect(
      calendarViewPath({
        calendarId: delegated.calendarId,
        mailboxEmail: calendarMailbox({ calendar: delegated, callerEmail: 'me@example.com' }),
      }),
    ).toBe('/users/banker@example.com/calendars/cal-2/calendarView');
  });
});

describe(calendarCollectionPath.name, () => {
  it('lists calendars under /users/{email}/calendars', () => {
    expect(calendarCollectionPath('me@example.com')).toBe('/users/me@example.com/calendars');
  });
});

describe(getSchedulePath.name, () => {
  it('posts getSchedule on /users/{email}/calendar', () => {
    expect(getSchedulePath('me@example.com')).toBe('/users/me@example.com/calendar/getSchedule');
  });

  it('rejects a mailbox that is not an SMTP address', () => {
    expect(() => getSchedulePath('evil/calendar')).toThrow(/SMTP/i);
  });
});

describe(findMeetingTimesPath.name, () => {
  it('posts findMeetingTimes on /users/{email}', () => {
    expect(findMeetingTimesPath('me@example.com')).toBe('/users/me@example.com/findMeetingTimes');
  });
});
