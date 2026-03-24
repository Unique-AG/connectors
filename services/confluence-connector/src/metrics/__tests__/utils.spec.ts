import { describe, expect, it } from 'vitest';
import { getHttpStatusCodeClass } from '../utils';

describe('getHttpStatusCodeClass', () => {
  it('returns 2xx for success status codes', () => {
    expect(getHttpStatusCodeClass(200)).toBe('2xx');
    expect(getHttpStatusCodeClass(204)).toBe('2xx');
    expect(getHttpStatusCodeClass(299)).toBe('2xx');
  });

  it('returns 3xx for redirect status codes', () => {
    expect(getHttpStatusCodeClass(301)).toBe('3xx');
    expect(getHttpStatusCodeClass(304)).toBe('3xx');
  });

  it('returns the exact code for 4xx client errors', () => {
    expect(getHttpStatusCodeClass(400)).toBe('400');
    expect(getHttpStatusCodeClass(401)).toBe('401');
    expect(getHttpStatusCodeClass(403)).toBe('403');
    expect(getHttpStatusCodeClass(404)).toBe('404');
    expect(getHttpStatusCodeClass(429)).toBe('429');
  });

  it('returns 5xx for server errors', () => {
    expect(getHttpStatusCodeClass(500)).toBe('5xx');
    expect(getHttpStatusCodeClass(502)).toBe('5xx');
    expect(getHttpStatusCodeClass(503)).toBe('5xx');
  });

  it('returns unknown for unexpected status codes', () => {
    expect(getHttpStatusCodeClass(0)).toBe('unknown');
    expect(getHttpStatusCodeClass(100)).toBe('unknown');
  });
});
