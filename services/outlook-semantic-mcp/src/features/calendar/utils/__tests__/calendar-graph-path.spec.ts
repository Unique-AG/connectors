import { describe, expect, it } from 'vitest';
import {
  calendarCollectionPath,
  calendarViewPath,
  createEventPath,
  defaultCalendarPath,
  encodeGraphQueryInstant,
  eventCancelPath,
  eventPath,
  eventResponsePath,
  findMeetingTimesPath,
  getSchedulePath,
} from '../calendar-graph-path';

describe(calendarViewPath.name, () => {
  it('reads the calendar view under /me, where every listed calendarId resolves', () => {
    expect(calendarViewPath('cal-1')).toBe('/me/calendars/cal-1/calendarView');
  });

  it('addresses a shared calendar the same way, because it is stored under the caller', () => {
    expect(calendarViewPath('cal-shared')).toBe('/me/calendars/cal-shared/calendarView');
  });
});

describe(encodeGraphQueryInstant.name, () => {
  it('percent-encodes a positive offset so Graph does not treat + as a space', () => {
    expect(encodeGraphQueryInstant('2026-08-24T00:00:00.000+02:00')).toBe(
      '2026-08-24T00:00:00.000%2B02:00',
    );
  });

  it('leaves UTC and negative offsets unchanged', () => {
    expect(encodeGraphQueryInstant('2026-08-24T00:00:00.000Z')).toBe('2026-08-24T00:00:00.000Z');
    expect(encodeGraphQueryInstant('2026-08-24T00:00:00.000-07:00')).toBe(
      '2026-08-24T00:00:00.000-07:00',
    );
  });
});

describe(calendarCollectionPath.name, () => {
  it('lists calendars under /me/calendars', () => {
    expect(calendarCollectionPath()).toBe('/me/calendars');
  });
});

describe(getSchedulePath.name, () => {
  it('posts getSchedule on /me/calendar', () => {
    expect(getSchedulePath()).toBe('/me/calendar/getSchedule');
  });
});

describe(findMeetingTimesPath.name, () => {
  it('posts findMeetingTimes on /me', () => {
    expect(findMeetingTimesPath()).toBe('/me/findMeetingTimes');
  });
});

describe(defaultCalendarPath.name, () => {
  it('gets the default calendar on /me/calendar', () => {
    expect(defaultCalendarPath()).toBe('/me/calendar');
  });
});

describe(createEventPath.name, () => {
  it('posts events on /me/calendars/{id}/events', () => {
    expect(createEventPath('cal-1')).toBe('/me/calendars/cal-1/events');
  });

  it('percent-encodes calendarId so slashes stay one path segment', () => {
    expect(createEventPath('x/../../../users/victim')).toBe(
      '/me/calendars/x%2F..%2F..%2F..%2Fusers%2Fvictim/events',
    );
  });

  it('rejects an empty calendarId instead of posting to the collection', () => {
    expect(() => createEventPath('')).toThrow(/calendarId/i);
  });
});

describe(eventPath.name, () => {
  it('gets or patches the event on /me/calendars/{id}/events/{id}', () => {
    expect(eventPath({ calendarId: 'cal-1', eventId: 'evt-1' })).toBe(
      '/me/calendars/cal-1/events/evt-1',
    );
  });
});

describe(eventCancelPath.name, () => {
  it('posts cancel on the event path, not DELETE', () => {
    expect(eventCancelPath({ calendarId: 'cal-1', eventId: 'evt-1' })).toBe(
      '/me/calendars/cal-1/events/evt-1/cancel',
    );
  });
});

describe(eventResponsePath.name, () => {
  it('posts the response on /me/calendars/{id}/events/{id}/{action}', () => {
    expect(eventResponsePath({ calendarId: 'cal-1', eventId: 'evt-1', response: 'accept' })).toBe(
      '/me/calendars/cal-1/events/evt-1/accept',
    );
  });

  it('percent-encodes Graph ids so slashes stay one path segment', () => {
    expect(eventResponsePath({ calendarId: 'cal/a', eventId: 'evt/b', response: 'decline' })).toBe(
      '/me/calendars/cal%2Fa/events/evt%2Fb/decline',
    );
  });
});
