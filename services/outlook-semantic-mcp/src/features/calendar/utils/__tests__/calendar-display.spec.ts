import { describe, expect, it } from 'vitest';
import { describeCalendar, formatDisplayWhen } from '../calendar-display';

describe(formatDisplayWhen.name, () => {
  it('formats Graph calendarView datetimes instead of dumping seven fractional digits', () => {
    expect(
      formatDisplayWhen(
        { dateTime: '2026-08-28T11:00:00.0000000', timeZone: 'W. Europe Standard Time' },
        { dateTime: '2026-08-28T12:00:00.0000000', timeZone: 'W. Europe Standard Time' },
      ),
    ).toBe('Fri 28 Aug 2026, 11:00–12:00 GMT+2');
  });

  it('formats an offset-bearing Instant on a single day as a range', () => {
    expect(formatDisplayWhen('2026-08-26T09:00:00+02:00', '2026-08-26T09:30:00+02:00')).toBe(
      'Wed 26 Aug 2026, 09:00–09:30 GMT+2',
    );
  });

  it('keeps both dates when the range crosses midnight', () => {
    expect(formatDisplayWhen('2026-08-26T23:00:00+02:00', '2026-08-27T01:00:00+02:00')).toBe(
      'Wed 26 Aug 2026, 23:00 – Thu 27 Aug 2026, 01:00 GMT+2',
    );
  });

  it('formats UTC as GMT', () => {
    expect(formatDisplayWhen('2026-08-26T09:00:00Z')).toBe('Wed 26 Aug 2026, 09:00 GMT');
  });

  it('formats a negative offset', () => {
    expect(formatDisplayWhen('2026-08-26T09:00:00-07:00')).toBe('Wed 26 Aug 2026, 09:00 GMT-7');
  });

  it('formats a fractional offset', () => {
    expect(formatDisplayWhen('2026-08-26T09:00:00+05:30')).toBe('Wed 26 Aug 2026, 09:00 GMT+5:30');
  });

  it('formats a Graph wall clock without a timezone rather than returning the raw ISO', () => {
    expect(formatDisplayWhen({ dateTime: '2026-08-28T11:00:00.0000000', timeZone: null })).toBe(
      'Fri 28 Aug 2026, 11:00',
    );
  });

  it('returns undefined when start is missing', () => {
    expect(formatDisplayWhen(null)).toBeUndefined();
    expect(formatDisplayWhen(undefined)).toBeUndefined();
  });
});

describe(describeCalendar.name, () => {
  it('names the signed-in user primary calendar', () => {
    expect(
      describeCalendar({
        name: 'Calendar',
        isDefaultCalendar: true,
        isOwn: true,
        ownerEmail: 'me@example.com',
        ownerName: 'Me',
      }),
    ).toBe('"Calendar" — your primary calendar');
  });
});
