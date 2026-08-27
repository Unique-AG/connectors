import { describe, expect, it } from 'vitest';
import {
  isSeriesOccurrence,
  parseGraphEventType,
  parseSeriesScope,
  resolveWriteEventId,
} from '../resolve-write-event-id';

describe(parseGraphEventType.name, () => {
  it('keeps occurrence, exception, and seriesMaster', () => {
    expect(parseGraphEventType('occurrence')).toBe('occurrence');
    expect(parseGraphEventType('exception')).toBe('exception');
    expect(parseGraphEventType('seriesMaster')).toBe('seriesMaster');
  });

  it('treats unknown types as a single instance', () => {
    expect(parseGraphEventType('singleInstance')).toBe('singleInstance');
    expect(parseGraphEventType('weird')).toBe('singleInstance');
    expect(parseGraphEventType(undefined)).toBe('singleInstance');
  });
});

describe(isSeriesOccurrence.name, () => {
  it('is true only for occurrence and exception', () => {
    expect(isSeriesOccurrence('occurrence')).toBe(true);
    expect(isSeriesOccurrence('exception')).toBe(true);
    expect(isSeriesOccurrence('seriesMaster')).toBe(false);
    expect(isSeriesOccurrence('singleInstance')).toBe(false);
  });
});

describe(parseSeriesScope.name, () => {
  it('reads thisOccurrence and entireSeries and ignores anything else', () => {
    expect(parseSeriesScope({ applyTo: 'entireSeries' })).toBe('entireSeries');
    expect(parseSeriesScope({ applyTo: 'thisOccurrence' })).toBe('thisOccurrence');
    expect(parseSeriesScope({ applyTo: 'all' })).toBeUndefined();
    expect(parseSeriesScope({})).toBeUndefined();
  });
});

describe(resolveWriteEventId.name, () => {
  it('returns the series master when applyTo is entireSeries', () => {
    expect(
      resolveWriteEventId({
        eventId: 'occ-1',
        seriesMasterId: 'master-1',
        applyTo: 'entireSeries',
      }),
    ).toBe('master-1');
  });

  it('returns the occurrence id otherwise', () => {
    expect(
      resolveWriteEventId({
        eventId: 'occ-1',
        seriesMasterId: 'master-1',
        applyTo: 'thisOccurrence',
      }),
    ).toBe('occ-1');
  });

  it('asserts a series master id when entireSeries is requested', () => {
    expect(() =>
      resolveWriteEventId({ eventId: 'occ-1', seriesMasterId: null, applyTo: 'entireSeries' }),
    ).toThrow(/seriesMasterId/);
  });
});
