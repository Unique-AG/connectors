import { describe, expect, it } from 'vitest';
import { convertDateTimeToTimezone } from './convert-datetime-to-timezone';

describe('convertDateTimeToTimezone', () => {
  it('returns falsy inputs unchanged', () => {
    expect(convertDateTimeToTimezone(null, 'Europe/Zurich')).toBeNull();
    expect(convertDateTimeToTimezone(undefined, 'Europe/Zurich')).toBeUndefined();
    expect(convertDateTimeToTimezone('', 'Europe/Zurich')).toBe('');
  });

  it('returns utcString unchanged when timezone is undefined', () => {
    expect(convertDateTimeToTimezone('2024-01-15T12:00:00Z', undefined)).toBe(
      '2024-01-15T12:00:00Z',
    );
  });

  it('returns utcString unchanged for an invalid date string', () => {
    expect(convertDateTimeToTimezone('not-a-date', 'Europe/Zurich')).toBe('not-a-date');
  });

  it('converts to UTC+0 correctly', () => {
    expect(convertDateTimeToTimezone('2024-01-15T12:00:00Z', 'UTC')).toBe(
      '2024-01-15T12:00:00+00:00',
    );
  });

  it('converts to a positive whole-hour offset (Europe/Zurich, winter UTC+1)', () => {
    expect(convertDateTimeToTimezone('2024-01-15T12:00:00Z', 'Europe/Zurich')).toBe(
      '2024-01-15T13:00:00+01:00',
    );
  });

  it('converts to a positive whole-hour offset with DST (Europe/Zurich, summer UTC+2)', () => {
    expect(convertDateTimeToTimezone('2024-07-15T10:00:00Z', 'Europe/Zurich')).toBe(
      '2024-07-15T12:00:00+02:00',
    );
  });

  it('converts to a negative offset (America/New_York, winter UTC-5)', () => {
    expect(convertDateTimeToTimezone('2024-01-15T17:00:00Z', 'America/New_York')).toBe(
      '2024-01-15T12:00:00-05:00',
    );
  });

  it('converts to a negative offset with DST (America/New_York, summer UTC-4)', () => {
    expect(convertDateTimeToTimezone('2024-07-15T16:00:00Z', 'America/New_York')).toBe(
      '2024-07-15T12:00:00-04:00',
    );
  });

  it('converts to a fractional offset (Asia/Kolkata UTC+5:30)', () => {
    expect(convertDateTimeToTimezone('2024-01-15T06:30:00Z', 'Asia/Kolkata')).toBe(
      '2024-01-15T12:00:00+05:30',
    );
  });

  it('handles midnight correctly without advancing the day (Europe/Zurich, winter)', () => {
    // 23:00 UTC = 00:00 next day in UTC+1 — hour should be 00 and day should advance
    expect(convertDateTimeToTimezone('2024-01-15T23:00:00Z', 'Europe/Zurich')).toBe(
      '2024-01-16T00:00:00+01:00',
    );
  });

  describe('Windows timezone names (as returned by Microsoft Graph)', () => {
    it('converts "Eastern Standard Time" the same as "America/New_York"', () => {
      expect(convertDateTimeToTimezone('2024-01-15T17:00:00Z', 'Eastern Standard Time')).toBe(
        '2024-01-15T12:00:00-05:00',
      );
    });

    it('converts "W. Europe Standard Time" the same as "Europe/Berlin" (winter UTC+1)', () => {
      expect(convertDateTimeToTimezone('2024-01-15T12:00:00Z', 'W. Europe Standard Time')).toBe(
        '2024-01-15T13:00:00+01:00',
      );
    });

    it('converts "India Standard Time" the same as "Asia/Kolkata" (UTC+5:30)', () => {
      expect(convertDateTimeToTimezone('2024-01-15T06:30:00Z', 'India Standard Time')).toBe(
        '2024-01-15T12:00:00+05:30',
      );
    });

    it('returns utcString unchanged for a completely unknown timezone name', () => {
      expect(convertDateTimeToTimezone('2024-01-15T12:00:00Z', 'Not A Real Timezone')).toBe(
        '2024-01-15T12:00:00Z',
      );
    });
  });
});
