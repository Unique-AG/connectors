import { describe, expect, it } from 'vitest';
import { clampToValidDate } from './clamp-to-valid-date';

describe('clampToValidDate', () => {
  it('passes through non-string values unchanged', () => {
    expect(clampToValidDate(null)).toBeNull();
    expect(clampToValidDate(42)).toBe(42);
    expect(clampToValidDate(undefined)).toBeUndefined();
  });

  it('passes through strings that do not match ISO datetime format', () => {
    expect(clampToValidDate('not-a-date')).toBe('not-a-date');
    expect(clampToValidDate('2026-02-29')).toBe('2026-02-29');
  });

  it('passes through valid dates unchanged', () => {
    expect(clampToValidDate('2026-02-28T23:59:59Z')).toBe('2026-02-28T23:59:59Z');
    expect(clampToValidDate('2026-01-31T00:00:00Z')).toBe('2026-01-31T00:00:00Z');
    expect(clampToValidDate('2026-03-31T12:00:00Z')).toBe('2026-03-31T12:00:00Z');
  });

  it('clamps Feb 29 to Feb 28 in a non-leap year', () => {
    expect(clampToValidDate('2026-02-29T23:59:59Z')).toBe('2026-02-28T23:59:59Z');
    expect(clampToValidDate('2025-02-29T00:00:00Z')).toBe('2025-02-28T00:00:00Z');
  });

  it('allows Feb 29 in a leap year', () => {
    expect(clampToValidDate('2024-02-29T00:00:00Z')).toBe('2024-02-29T00:00:00Z');
    expect(clampToValidDate('2028-02-29T23:59:59Z')).toBe('2028-02-29T23:59:59Z');
  });

  it('clamps day 31 to day 30 in months with 30 days', () => {
    expect(clampToValidDate('2026-04-31T00:00:00Z')).toBe('2026-04-30T00:00:00Z');
    expect(clampToValidDate('2026-06-31T00:00:00Z')).toBe('2026-06-30T00:00:00Z');
    expect(clampToValidDate('2026-11-31T12:00:00Z')).toBe('2026-11-30T12:00:00Z');
  });
});
