import { Temporal } from 'temporal-polyfill';
import { describe, expect, it } from 'vitest';
import { decodeAvailabilityView } from '../decode-availability-view';

describe(decodeAvailabilityView.name, () => {
  it('merges consecutive non-free slots from the Graph bitmap example', () => {
    const start = Temporal.ZonedDateTime.from('2019-03-15T09:00:00[America/Los_Angeles]');

    expect(
      decodeAvailabilityView({
        availabilityView: '000220130',
        start,
        intervalMinutes: 60,
      }),
    ).toEqual([
      {
        status: 'busy',
        startDateTime: '2019-03-15T12:00:00.000-07:00',
        endDateTime: '2019-03-15T14:00:00.000-07:00',
      },
      {
        status: 'tentative',
        startDateTime: '2019-03-15T15:00:00.000-07:00',
        endDateTime: '2019-03-15T16:00:00.000-07:00',
      },
      {
        status: 'oof',
        startDateTime: '2019-03-15T16:00:00.000-07:00',
        endDateTime: '2019-03-15T17:00:00.000-07:00',
      },
    ]);
  });

  it('maps workingElsewhere (4) and unknown codes and skips free (0)', () => {
    const start = Temporal.ZonedDateTime.from('2026-08-25T09:00:00[Europe/Zurich]');

    expect(
      decodeAvailabilityView({
        availabilityView: '0405',
        start,
        intervalMinutes: 30,
      }),
    ).toEqual([
      {
        status: 'workingElsewhere',
        startDateTime: '2026-08-25T09:30:00.000+02:00',
        endDateTime: '2026-08-25T10:00:00.000+02:00',
      },
      {
        status: 'unknown',
        startDateTime: '2026-08-25T10:30:00.000+02:00',
        endDateTime: '2026-08-25T11:00:00.000+02:00',
      },
    ]);
  });

  it('returns no blocks for an empty or all-free view', () => {
    const start = Temporal.ZonedDateTime.from('2026-08-25T09:00:00[UTC]');

    expect(decodeAvailabilityView({ availabilityView: '', start, intervalMinutes: 30 })).toEqual(
      [],
    );
    expect(decodeAvailabilityView({ availabilityView: '000', start, intervalMinutes: 30 })).toEqual(
      [],
    );
  });
});
