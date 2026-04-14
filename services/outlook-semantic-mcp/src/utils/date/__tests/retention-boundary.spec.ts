import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { computeRetentionCutoffDate } from '../compute-retention-cutoff-date';
import { getMessageExpirationDate } from '../get-message-expiration-date';

// Freeze at a mid-day UTC time so UTC-midnight truncation is non-trivial.
const FIXED_NOW = new Date('2025-06-15T14:32:00.000Z');

describe('retention boundary: computeRetentionCutoffDate and getExpirationDate are aligned', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const RETENTION_DAYS = 30;

  it('the oldest message that passes the cutoff is still within its expiration window', () => {
    const cutoff = computeRetentionCutoffDate(RETENTION_DAYS);

    // Oldest message that passes: received exactly at the cutoff timestamp.
    const receivedDateTime = cutoff.toISOString();
    const expiration = getMessageExpirationDate({
      receivedDateTime,
      retentionWindowInDays: RETENTION_DAYS,
    });

    expect(new Date(receivedDateTime) >= cutoff).toBe(true);
    expect(expiration > FIXED_NOW).toBe(true);
  });

  it('a message received 1 ms before the cutoff is before the cutoff and already expired', () => {
    const cutoff = computeRetentionCutoffDate(RETENTION_DAYS);

    // One millisecond before the cutoff — just outside the retention window.
    const receivedDateTime = new Date(cutoff.getTime() - 1).toISOString();
    const expiration = getMessageExpirationDate({
      receivedDateTime,
      retentionWindowInDays: RETENTION_DAYS,
    });

    expect(new Date(receivedDateTime) < cutoff).toBe(true);
    expect(expiration < FIXED_NOW).toBe(true);
  });

  it('expiration of the boundary message is exactly end of today UTC', () => {
    const cutoff = computeRetentionCutoffDate(RETENTION_DAYS);

    // Message received at the cutoff = UTC midnight of (today - RETENTION_DAYS).
    // Expiration = end of (today - RETENTION_DAYS + RETENTION_DAYS) = end of today.
    const expiration = getMessageExpirationDate({
      receivedDateTime: cutoff,
      retentionWindowInDays: RETENTION_DAYS,
    });

    const endOfToday = new Date(FIXED_NOW);
    endOfToday.setUTCHours(23, 59, 59, 999);

    expect(expiration.toISOString()).toBe(endOfToday.toISOString());
  });
});
