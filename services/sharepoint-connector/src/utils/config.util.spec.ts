import { describe, expect, it } from 'vitest';
import { parseJsonOrPassthrough } from './config.util';

describe('parseJsonOrPassthrough', () => {
  it('parses a valid JSON array string', () => {
    expect(parseJsonOrPassthrough('["on_startup","per_sync"]')).toEqual(['on_startup', 'per_sync']);
  });

  it('parses a valid JSON object string', () => {
    expect(parseJsonOrPassthrough('{"key":"value"}')).toEqual({ key: 'value' });
  });

  it('parses a JSON number string', () => {
    expect(parseJsonOrPassthrough('42')).toBe(42);
  });

  it('returns the original string when JSON.parse fails', () => {
    expect(parseJsonOrPassthrough('none')).toBe('none');
  });

  it('returns the original string for malformed JSON', () => {
    expect(parseJsonOrPassthrough('[invalid')).toBe('[invalid');
  });

  it('passes through an array value unchanged', () => {
    const arr = ['on_startup', 'per_sync'];
    expect(parseJsonOrPassthrough(arr)).toBe(arr);
  });

  it('passes through an object value unchanged', () => {
    const obj = { key: 'value' };
    expect(parseJsonOrPassthrough(obj)).toBe(obj);
  });

  it('passes through undefined', () => {
    expect(parseJsonOrPassthrough(undefined)).toBeUndefined();
  });

  it('passes through null', () => {
    expect(parseJsonOrPassthrough(null)).toBeNull();
  });

  it('passes through a number', () => {
    expect(parseJsonOrPassthrough(123)).toBe(123);
  });
});
