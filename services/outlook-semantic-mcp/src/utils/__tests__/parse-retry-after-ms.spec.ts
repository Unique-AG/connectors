import { describe, expect, it } from 'vitest';
import { parseRetryAfterMs } from '../parse-retry-after-ms';

describe('parseRetryAfterMs', () => {
  const now = Date.parse('2026-11-24T10:00:00.000Z');

  it('reads delay-seconds', () => {
    expect(parseRetryAfterMs('300', now)).toBe(300_000);
  });

  it('reads an HTTP date as the time left until it', () => {
    expect(parseRetryAfterMs('Tue, 24 Nov 2026 10:05:00 GMT', now)).toBe(300_000);
  });

  it('reads an HTTP date already past as no wait', () => {
    expect(parseRetryAfterMs('Tue, 24 Nov 2026 09:55:00 GMT', now)).toBe(0);
  });

  it('returns null for a missing, negative or unreadable value', () => {
    expect(parseRetryAfterMs(null, now)).toBeNull();
    expect(parseRetryAfterMs(undefined, now)).toBeNull();
    expect(parseRetryAfterMs('', now)).toBeNull();
    expect(parseRetryAfterMs('-5', now)).toBeNull();
    expect(parseRetryAfterMs('soon', now)).toBeNull();
  });
});
