import { describe, expect, it } from 'vitest';
import { computeIgnoredBefore } from './inbox-configuration-mail-filters.dto';

describe('computeIgnoredBefore', () => {
  it('returns midnight of the date that is N days ago', () => {
    const result = computeIgnoredBefore(30);
    const expected = new Date();
    expected.setDate(expected.getDate() - 30);
    expected.setHours(0, 0, 0, 0);

    expect(result.getFullYear()).toBe(expected.getFullYear());
    expect(result.getMonth()).toBe(expected.getMonth());
    expect(result.getDate()).toBe(expected.getDate());
  });

  it('truncates time to midnight', () => {
    const result = computeIgnoredBefore(1);
    expect(result.getHours()).toBe(0);
    expect(result.getMinutes()).toBe(0);
    expect(result.getSeconds()).toBe(0);
    expect(result.getMilliseconds()).toBe(0);
  });

  it('subtracts the correct number of days', () => {
    const result = computeIgnoredBefore(365);
    const expected = new Date();
    expected.setDate(expected.getDate() - 365);
    expected.setHours(0, 0, 0, 0);

    expect(result.getTime()).toBe(expected.getTime());
  });
});
