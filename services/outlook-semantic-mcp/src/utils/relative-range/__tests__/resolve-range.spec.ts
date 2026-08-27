import { Temporal } from 'temporal-polyfill';
import { describe, expect, it } from 'vitest';
import { RELATIVE_RANGES } from '../relative-range';
import { resolveRange } from '../resolve-range';

const ZURICH = 'Europe/Zurich';
const TUESDAY = Temporal.ZonedDateTime.from('2026-08-25T15:30:00[Europe/Zurich]');

const TUESDAY_BOUNDS: Record<(typeof RELATIVE_RANGES)[number], { start: string; end: string }> = {
  today: { start: '2026-08-25T00:00:00.000+02:00', end: '2026-08-25T23:59:59.999+02:00' },
  tomorrow: { start: '2026-08-26T00:00:00.000+02:00', end: '2026-08-26T23:59:59.999+02:00' },
  yesterday: { start: '2026-08-24T00:00:00.000+02:00', end: '2026-08-24T23:59:59.999+02:00' },
  thisWeek: { start: '2026-08-24T00:00:00.000+02:00', end: '2026-08-30T23:59:59.999+02:00' },
  nextWeek: { start: '2026-08-31T00:00:00.000+02:00', end: '2026-09-06T23:59:59.999+02:00' },
  lastWeek: { start: '2026-08-17T00:00:00.000+02:00', end: '2026-08-23T23:59:59.999+02:00' },
  thisMonth: { start: '2026-08-01T00:00:00.000+02:00', end: '2026-08-31T23:59:59.999+02:00' },
  nextMonth: { start: '2026-09-01T00:00:00.000+02:00', end: '2026-09-30T23:59:59.999+02:00' },
  lastMonth: { start: '2026-07-01T00:00:00.000+02:00', end: '2026-07-31T23:59:59.999+02:00' },
  thisYear: { start: '2026-01-01T00:00:00.000+01:00', end: '2026-12-31T23:59:59.999+01:00' },
  nextYear: { start: '2027-01-01T00:00:00.000+01:00', end: '2027-12-31T23:59:59.999+01:00' },
  lastYear: { start: '2025-01-01T00:00:00.000+01:00', end: '2025-12-31T23:59:59.999+01:00' },
  next7Days: { start: '2026-08-25T15:30:00.000+02:00', end: '2026-09-01T15:30:00.000+02:00' },
  next30Days: { start: '2026-08-25T15:30:00.000+02:00', end: '2026-09-24T15:30:00.000+02:00' },
  next90Days: { start: '2026-08-25T15:30:00.000+02:00', end: '2026-11-23T15:30:00.000+01:00' },
  past7Days: { start: '2026-08-18T15:30:00.000+02:00', end: '2026-08-25T15:30:00.000+02:00' },
  past30Days: { start: '2026-07-26T15:30:00.000+02:00', end: '2026-08-25T15:30:00.000+02:00' },
};

describe(resolveRange.name, () => {
  it.each(RELATIVE_RANGES)('resolves %s from a Tuesday in Zurich', (range) => {
    const result = resolveRange({ range, now: TUESDAY });
    const bounds = TUESDAY_BOUNDS[range];

    expect(result.startDateTime).toBe(bounds.start);
    expect(result.endDateTime).toBe(bounds.end);
    expect(result.timeZone).toBe(ZURICH);
  });

  it('resolves today as the mailbox-local calendar day', () => {
    const result = resolveRange({ range: 'today', now: TUESDAY });

    expect(result.interpretation).toBe(
      'today = Tue 2026-08-25 00:00 to Tue 2026-08-25 23:59 (Europe/Zurich)',
    );
    expect(result.serverCurrentDateTime).toBe('2026-08-25T15:30:00.000+02:00');
  });

  it('resolves thisWeek as Monday–Sunday of the ISO week containing now', () => {
    const result = resolveRange({ range: 'thisWeek', now: TUESDAY });

    expect(result.interpretation).toContain(
      'this week = Mon 2026-08-24 00:00 to Sun 2026-08-30 23:59',
    );
  });

  it('resolves nextWeek from a Sunday as the following Monday–Sunday', () => {
    const sunday = Temporal.ZonedDateTime.from('2026-08-30T10:00:00[Europe/Zurich]');
    const result = resolveRange({ range: 'nextWeek', now: sunday });

    expect(result.startDateTime).toBe('2026-08-31T00:00:00.000+02:00');
    expect(result.endDateTime).toBe('2026-09-06T23:59:59.999+02:00');
  });

  it("uses each boundary's own DST offset", () => {
    const midMarch = Temporal.ZonedDateTime.from('2026-03-15T12:00:00[Europe/Zurich]');
    const result = resolveRange({ range: 'thisMonth', now: midMarch });

    expect(result.startDateTime).toBe('2026-03-01T00:00:00.000+01:00');
    expect(result.endDateTime).toBe('2026-03-31T23:59:59.999+02:00');
  });

  it('ends a calendar day before a midnight spring-forward without overshooting', () => {
    const now = Temporal.ZonedDateTime.from('2026-09-05T12:00:00[America/Santiago]');
    const result = resolveRange({ range: 'today', now });

    expect(result.endDateTime).toBe('2026-09-05T23:59:59.999-04:00');
    expect(result.timeZone).toBe('America/Santiago');
  });
});
