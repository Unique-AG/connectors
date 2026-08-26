import { describe, expect, it } from 'vitest';
import type { CalendarRef } from '../../calendar.schemas';
import {
  calendarCollectionPath,
  calendarViewPath,
  createEventPath,
  defaultCalendarPath,
  eventCancelPath,
  eventPath,
  eventResponsePath,
  findMeetingTimesPath,
  getSchedulePath,
} from '../calendar-graph-path';

const own: CalendarRef = {
  calendarId: 'cal-1',
  name: 'Calendar',
  mailbox: 'me@example.com',
  ownerEmail: 'me@example.com',
  ownerName: 'Me',
  isOwn: true,
  isDefaultCalendar: true,
  canEdit: true,
  canViewPrivateItems: true,
};

const delegated: CalendarRef = {
  calendarId: 'cal-2',
  name: 'Banker',
  mailbox: 'banker@example.com',
  ownerEmail: 'banker@example.com',
  ownerName: 'Banker',
  isOwn: false,
  isDefaultCalendar: true,
  canEdit: true,
  canViewPrivateItems: false,
};

describe(calendarViewPath.name, () => {
  it('always uses /users/{email}/calendars for the caller mailbox', () => {
    expect(calendarViewPath({ calendarId: own.calendarId, mailboxEmail: 'me@example.com' })).toBe(
      '/users/me@example.com/calendars/cal-1/calendarView',
    );
  });

  it('uses the mailbox the calendar was listed from', () => {
    expect(
      calendarViewPath({ calendarId: delegated.calendarId, mailboxEmail: delegated.mailbox }),
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

describe(defaultCalendarPath.name, () => {
  it('gets the default calendar on /users/{email}/calendar', () => {
    expect(defaultCalendarPath('me@example.com')).toBe('/users/me@example.com/calendar');
  });
});

describe(createEventPath.name, () => {
  it('posts events on /users/{email}/calendars/{id}/events', () => {
    expect(createEventPath({ mailboxEmail: 'me@example.com', calendarId: 'cal-1' })).toBe(
      '/users/me@example.com/calendars/cal-1/events',
    );
  });

  it('rejects a mailbox that is not an SMTP address', () => {
    expect(() => createEventPath({ mailboxEmail: 'evil/calendar', calendarId: 'cal-1' })).toThrow(
      /SMTP/i,
    );
  });

  it('percent-encodes calendarId so slashes stay one path segment', () => {
    expect(
      createEventPath({ mailboxEmail: 'me@example.com', calendarId: 'x/../../../users/victim' }),
    ).toBe('/users/me@example.com/calendars/x%2F..%2F..%2F..%2Fusers%2Fvictim/events');
  });
});

describe(eventPath.name, () => {
  it('gets or patches the event on /users/{email}/calendars/{id}/events/{id}', () => {
    expect(
      eventPath({
        mailboxEmail: 'me@example.com',
        calendarId: 'cal-1',
        eventId: 'evt-1',
      }),
    ).toBe('/users/me@example.com/calendars/cal-1/events/evt-1');
  });
});

describe(eventCancelPath.name, () => {
  it('posts cancel on the event path, not DELETE', () => {
    expect(
      eventCancelPath({
        mailboxEmail: 'me@example.com',
        calendarId: 'cal-1',
        eventId: 'evt-1',
      }),
    ).toBe('/users/me@example.com/calendars/cal-1/events/evt-1/cancel');
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

  it('percent-encodes Graph ids so slashes stay one path segment', () => {
    expect(
      eventResponsePath({
        mailboxEmail: 'me@example.com',
        calendarId: 'cal/a',
        eventId: 'evt/b',
        response: 'decline',
      }),
    ).toBe('/users/me@example.com/calendars/cal%2Fa/events/evt%2Fb/decline');
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
