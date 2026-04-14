import { describe, expect, it } from 'vitest';
import { getMessageExpirationDate } from '../get-message-expiration-date';

describe('getMessageExpirationDate', () => {
  it('returns end of the last retention day in UTC for a mid-day receivedDateTime string', () => {
    // received 2025-05-16T14:32:00Z, retention 30 days
    // → UTC midnight of received day = 2025-05-16T00:00:00Z
    // → + 31 days = 2025-06-16T00:00:00Z
    // → - 1ms   = 2025-06-15T23:59:59.999Z
    const result = getMessageExpirationDate({
      receivedDateTime: '2025-05-16T14:32:00.000Z',
      retentionWindowInDays: 30,
    });
    expect(result.toISOString()).toBe('2025-06-15T23:59:59.999Z');
  });

  it('returns end of the last retention day in UTC for a UTC-midnight receivedDateTime', () => {
    const result = getMessageExpirationDate({
      receivedDateTime: '2025-05-16T00:00:00.000Z',
      retentionWindowInDays: 30,
    });
    expect(result.toISOString()).toBe('2025-06-15T23:59:59.999Z');
  });

  it('accepts a Date object as receivedDateTime', () => {
    const result = getMessageExpirationDate({
      receivedDateTime: new Date('2025-05-16T14:32:00.000Z'),
      retentionWindowInDays: 30,
    });
    expect(result.toISOString()).toBe('2025-06-15T23:59:59.999Z');
  });

  it('expiration is at 23:59:59.999 UTC (end of day)', () => {
    const result = getMessageExpirationDate({
      receivedDateTime: '2025-01-01T00:00:00.000Z',
      retentionWindowInDays: 7,
    });
    expect(result.getUTCHours()).toBe(23);
    expect(result.getUTCMinutes()).toBe(59);
    expect(result.getUTCSeconds()).toBe(59);
    expect(result.getUTCMilliseconds()).toBe(999);
  });

  it('works for a 1-day retention window', () => {
    // received 2025-06-15, retention 1 day → expires end of 2025-06-16
    const result = getMessageExpirationDate({
      receivedDateTime: '2025-06-15T00:00:00.000Z',
      retentionWindowInDays: 1,
    });
    expect(result.toISOString()).toBe('2025-06-16T23:59:59.999Z');
  });

  it('works for a 365-day retention window', () => {
    const result = getMessageExpirationDate({
      receivedDateTime: '2024-06-15T00:00:00.000Z',
      retentionWindowInDays: 365,
    });
    // 2024-06-15 + 366 days - 1ms = end of 2025-06-15
    expect(result.toISOString()).toBe('2025-06-15T23:59:59.999Z');
  });
});
