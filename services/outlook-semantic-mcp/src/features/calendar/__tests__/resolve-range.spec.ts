import { describe, expect, it } from 'vitest';
import { resolveRange } from '../resolve-range';

const ZURICH = 'Europe/Zurich';
const TUESDAY = Temporal.ZonedDateTime.from('2026-08-25T15:30:00[Europe/Zurich]');

describe(resolveRange.name, () => {
  it('resolves today as the mailbox-local calendar day', () => {
    const result = resolveRange('today', ZURICH, TUESDAY);

    expect(result).toEqual({
      startDateTime: '2026-08-25T00:00:00.000+02:00',
      endDateTime: '2026-08-25T23:59:59.999+02:00',
      timeZone: ZURICH,
      serverCurrentDateTime: '2026-08-25T15:30:00.000+02:00',
      interpretation: 'today = Tue 2026-08-25 00:00 to Tue 2026-08-25 23:59 (Europe/Zurich)',
    });
  });

  it('resolves thisWeek as Monday–Sunday of the ISO week containing now', () => {
    const result = resolveRange('thisWeek', ZURICH, TUESDAY);

    expect(result.startDateTime).toBe('2026-08-24T00:00:00.000+02:00');
    expect(result.endDateTime).toBe('2026-08-30T23:59:59.999+02:00');
    expect(result.interpretation).toContain(
      'this week = Mon 2026-08-24 00:00 to Sun 2026-08-30 23:59',
    );
  });

  it('resolves nextWeek from a Sunday as the following Monday–Sunday', () => {
    const sunday = Temporal.ZonedDateTime.from('2026-08-30T10:00:00[Europe/Zurich]');
    const result = resolveRange('nextWeek', ZURICH, sunday);

    expect(result.startDateTime).toBe('2026-08-31T00:00:00.000+02:00');
    expect(result.endDateTime).toBe('2026-09-06T23:59:59.999+02:00');
  });

  it('resolves lastMonth as the previous calendar month', () => {
    const result = resolveRange('lastMonth', ZURICH, TUESDAY);

    expect(result.startDateTime).toBe('2026-07-01T00:00:00.000+02:00');
    expect(result.endDateTime).toBe('2026-07-31T23:59:59.999+02:00');
  });

  it("uses each boundary's own DST offset", () => {
    const midMarch = Temporal.ZonedDateTime.from('2026-03-15T12:00:00[Europe/Zurich]');
    const result = resolveRange('thisMonth', ZURICH, midMarch);

    expect(result.startDateTime).toBe('2026-03-01T00:00:00.000+01:00');
    expect(result.endDateTime).toBe('2026-03-31T23:59:59.999+02:00');
  });

  it('resolves next7Days as a rolling window from now', () => {
    const result = resolveRange('next7Days', ZURICH, TUESDAY);

    expect(result.startDateTime).toBe('2026-08-25T15:30:00.000+02:00');
    expect(result.endDateTime).toBe('2026-09-01T15:30:00.000+02:00');
  });

  it('resolves past30Days as a rolling window backward from now', () => {
    const result = resolveRange('past30Days', ZURICH, TUESDAY);

    expect(result.startDateTime).toBe('2026-07-26T15:30:00.000+02:00');
    expect(result.endDateTime).toBe('2026-08-25T15:30:00.000+02:00');
  });
});
