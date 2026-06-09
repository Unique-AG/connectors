import { describe, expect, it } from 'vitest';
import { getMessageExpirationDate } from '../get-message-expiration-date';

describe('getMessageExpirationDate', () => {
  it('returns midnight UTC of the day after the last retention day for a mid-day receivedDateTime string', () => {
    // received 2025-05-16T14:32:00Z, retention 30 days
    // → UTC date of received day = May 16
    // → + (30+1) days = June 16
    // → start of UTC day = 2025-06-16T00:00:00.000Z
    const result = getMessageExpirationDate({
      receivedDateTime: '2025-05-16T14:32:00.000Z',
      retentionWindowInDays: 30,
    });
    expect(result.toISOString()).toBe('2025-06-16T00:00:00.000Z');
  });

  it('returns midnight UTC of the day after the last retention day for a UTC-midnight receivedDateTime', () => {
    const result = getMessageExpirationDate({
      receivedDateTime: '2025-05-16T00:00:00.000Z',
      retentionWindowInDays: 30,
    });
    expect(result.toISOString()).toBe('2025-06-16T00:00:00.000Z');
  });

  it('accepts a Date object as receivedDateTime', () => {
    const result = getMessageExpirationDate({
      receivedDateTime: new Date('2025-05-16T14:32:00.000Z'),
      retentionWindowInDays: 30,
    });
    expect(result.toISOString()).toBe('2025-06-16T00:00:00.000Z');
  });

  it('expiration is at 00:00:00.000 UTC (start of following day, exclusive boundary)', () => {
    const result = getMessageExpirationDate({
      receivedDateTime: '2025-01-01T00:00:00.000Z',
      retentionWindowInDays: 7,
    });
    expect(result.getUTCHours()).toBe(0);
    expect(result.getUTCMinutes()).toBe(0);
    expect(result.getUTCSeconds()).toBe(0);
    expect(result.getUTCMilliseconds()).toBe(0);
  });

  it('works for a 1-day retention window', () => {
    // received 2025-06-15, retention 1 day → expires start of 2025-06-17
    const result = getMessageExpirationDate({
      receivedDateTime: '2025-06-15T00:00:00.000Z',
      retentionWindowInDays: 1,
    });
    expect(result.toISOString()).toBe('2025-06-17T00:00:00.000Z');
  });

  it('works for a 365-day retention window', () => {
    const result = getMessageExpirationDate({
      receivedDateTime: '2024-06-15T00:00:00.000Z',
      retentionWindowInDays: 365,
    });
    // 2024-06-15 + 365 days = 2025-06-15, + 1 more day = start of 2025-06-16
    expect(result.toISOString()).toBe('2025-06-16T00:00:00.000Z');
  });
});
