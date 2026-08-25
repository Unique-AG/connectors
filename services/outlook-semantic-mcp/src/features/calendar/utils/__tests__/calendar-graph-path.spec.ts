import { describe, expect, it } from 'vitest';
import type { CalendarRef } from '../../calendar.schemas';
import {
  calendarCollectionPath,
  calendarMailbox,
  calendarViewPath,
  eventResponsePath,
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

describe(eventResponsePath.name, () => {
  it('posts the response on /users/{email}/calendars/{id}/events/{id}/{action}', () => {
    expect(
      eventResponsePath({
        mailboxEmail: 'me@example.com',
        calendarId: 'cal-1',
        eventId: 'evt-1',
        response: 'accept',
      }),
    ).toBe('/users/me@example.com/calendars/cal-1/events/evt-1/accept');
  });

  it('leaves Graph ids unchanged, matching calendarViewPath', () => {
    expect(
      eventResponsePath({
        mailboxEmail: 'me@example.com',
        calendarId: 'cal/a',
        eventId: 'evt/b',
        response: 'decline',
      }),
    ).toBe('/users/me@example.com/calendars/cal/a/events/evt/b/decline');
  });

  it('rejects a mailbox that is not an SMTP address', () => {
    expect(() =>
      eventResponsePath({
        mailboxEmail: 'evil/calendar',
        calendarId: 'cal-1',
        eventId: 'evt-1',
        response: 'accept',
      }),
    ).toThrow(/SMTP/i);
  });
});
