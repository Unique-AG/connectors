import { describe, expect, it } from 'vitest';
import { summariseRecurrence } from '../summarise-recurrence';

describe(summariseRecurrence.name, () => {
  it('returns null when Graph omitted recurrence', () => {
    expect(summariseRecurrence(undefined)).toBeNull();
  });

  it('summarises a weekly pattern', () => {
    expect(summariseRecurrence({ type: 'weekly', interval: 1, daysOfWeek: ['tuesday'] })).toBe(
      'Weekly on Tuesday',
    );
  });

  it('summarises a daily pattern', () => {
    expect(summariseRecurrence({ type: 'daily', interval: 1 })).toBe('Daily');
  });
});
