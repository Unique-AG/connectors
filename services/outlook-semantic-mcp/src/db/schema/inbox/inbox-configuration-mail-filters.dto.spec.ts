import { describe, expect, it } from 'vitest';
import { computeIgnoredBefore } from './inbox-configuration-mail-filters.dto';

describe('computeIgnoredBefore', () => {
  it('returns UTC midnight of the date that is N days ago', () => {
    const result = computeIgnoredBefore(30);
    const expected = new Date();
    expected.setDate(expected.getDate() - 30);
    expected.setUTCHours(0, 0, 0, 0);

    expect(result.getUTCFullYear()).toBe(expected.getUTCFullYear());
    expect(result.getUTCMonth()).toBe(expected.getUTCMonth());
    expect(result.getUTCDate()).toBe(expected.getUTCDate());
  });

  it('truncates time to UTC midnight', () => {
    const result = computeIgnoredBefore(1);
    expect(result.getUTCHours()).toBe(0);
    expect(result.getUTCMinutes()).toBe(0);
    expect(result.getUTCSeconds()).toBe(0);
    expect(result.getUTCMilliseconds()).toBe(0);
  });

  it('subtracts the correct number of days', () => {
    const result = computeIgnoredBefore(365);
    const expected = new Date();
    expected.setDate(expected.getDate() - 365);
    expected.setUTCHours(0, 0, 0, 0);

    expect(result.getTime()).toBe(expected.getTime());
  });
});
