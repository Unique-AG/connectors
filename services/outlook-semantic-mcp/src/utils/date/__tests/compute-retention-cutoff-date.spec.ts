import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { computeRetentionCutoffDate } from '~/utils/date/compute-retention-cutoff-date';

const FIXED_NOW = new Date('2025-06-15T14:32:00.000Z');

describe('computeRetentionCutoffDate', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns UTC midnight of the date that is N days ago', () => {
    const result = computeRetentionCutoffDate(30);
    const expected = new Date(FIXED_NOW);
    expected.setDate(expected.getDate() - 30);
    expected.setUTCHours(0, 0, 0, 0);

    expect(result.getUTCFullYear()).toBe(expected.getUTCFullYear());
    expect(result.getUTCMonth()).toBe(expected.getUTCMonth());
    expect(result.getUTCDate()).toBe(expected.getUTCDate());
    expect(result.getUTCHours()).toBe(0);
    expect(result.getUTCMinutes()).toBe(0);
    expect(result.getUTCSeconds()).toBe(0);
    expect(result.getUTCMilliseconds()).toBe(0);
  });

  it('truncates time to UTC midnight', () => {
    const result = computeRetentionCutoffDate(1);
    expect(result.getUTCHours()).toBe(0);
    expect(result.getUTCMinutes()).toBe(0);
    expect(result.getUTCSeconds()).toBe(0);
    expect(result.getUTCMilliseconds()).toBe(0);
  });

  it('subtracts the correct number of days', () => {
    const result = computeRetentionCutoffDate(365);
    const expected = new Date(FIXED_NOW);
    expected.setDate(expected.getDate() - 365);
    expected.setUTCHours(0, 0, 0, 0);

    expect(result.getTime()).toBe(expected.getTime());
  });
});
