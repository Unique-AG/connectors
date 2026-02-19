import { describe, expect, it } from 'vitest';
import { smear } from '../smeared';

describe('smear', () => {
  it('returns __erroneous__ for null input', () => {
    expect(smear(null)).toBe('__erroneous__');
  });

  it('returns __erroneous__ for undefined input', () => {
    expect(smear(undefined)).toBe('__erroneous__');
  });

  it('returns [Smeared] for empty string', () => {
    expect(smear('')).toBe('[Smeared]');
  });

  it('returns [Smeared] for strings shorter than or equal to leaveOver', () => {
    expect(smear('a')).toBe('[Smeared]');
    expect(smear('ab')).toBe('[Smeared]');
    expect(smear('abc')).toBe('[Smeared]');
    expect(smear('abcd')).toBe('[Smeared]');
  });

  it('returns [Smeared] for strings that would star fewer than 3 characters', () => {
    expect(smear('hello')).toBe('[Smeared]');
    expect(smear('world')).toBe('[Smeared]');
  });

  it('smears longer strings by replacing middle characters with asterisks', () => {
    expect(smear('password')).toBe('****word');
    expect(smear('mySecret123')).toBe('*******t123');
    expect(smear('verylongstring')).toBe('**********ring');
  });

  it('works with custom leaveOver parameter', () => {
    expect(smear('hello', 2)).toBe('***lo');
    expect(smear('password', 3)).toBe('*****ord');
  });
});
