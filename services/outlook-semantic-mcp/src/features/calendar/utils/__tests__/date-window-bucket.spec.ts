import { describe, expect, it } from 'vitest';
import { dateWindowBucket, dateWindowFromSearchInput } from '../date-window-bucket';

describe(dateWindowBucket.name, () => {
  it.each([
    {
      label: '<1week',
      start: '2026-08-25T00:00:00.000+02:00',
      end: '2026-08-31T23:59:59.999+02:00',
    },
    {
      label: '<1month',
      start: '2026-08-25T15:30:00.000+02:00',
      end: '2026-09-24T15:30:00.000+02:00',
    },
    {
      label: '<3months',
      start: '2026-08-25T15:30:00.000+02:00',
      end: '2026-11-23T15:30:00.000+01:00',
    },
    {
      label: '<6months',
      start: '2026-01-01T00:00:00.000Z',
      end: '2026-06-01T00:00:00.000Z',
    },
    {
      label: '<9months',
      start: '2026-01-01T00:00:00.000Z',
      end: '2026-09-01T00:00:00.000Z',
    },
    {
      label: '<1year',
      start: '2026-01-01T00:00:00.000+01:00',
      end: '2026-12-31T23:59:59.999+01:00',
    },
    {
      label: '<2years',
      start: '2025-01-01T00:00:00.000Z',
      end: '2026-07-01T00:00:00.000Z',
    },
    {
      label: '>2years',
      start: '2024-01-01T00:00:00.000Z',
      end: '2026-08-01T00:00:00.000Z',
    },
  ] as const)('buckets $start → $end as $label', ({ start, end, label }) => {
    expect(dateWindowBucket(start, end)).toBe(label);
  });

  it('returns unknown when the timestamps cannot be parsed', () => {
    expect(dateWindowBucket('not-a-date', '2026-01-01T00:00:00Z')).toBe('unknown');
  });
});

describe(dateWindowFromSearchInput.name, () => {
  it.each([
    ['today', '<1week'],
    ['thisWeek', '<1week'],
    ['next30Days', '<1month'],
    ['next90Days', '<3months'],
    ['thisYear', '<1year'],
  ] as const)('maps relative range %s to %s', (range, label) => {
    expect(dateWindowFromSearchInput({ range })).toBe(label);
  });

  it('buckets an absolute window from its timestamps', () => {
    expect(
      dateWindowFromSearchInput({
        startDateTime: '2026-01-01T00:00:00.000Z',
        endDateTime: '2026-06-01T00:00:00.000Z',
      }),
    ).toBe('<6months');
  });
});
