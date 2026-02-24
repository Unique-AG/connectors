import { describe, expect, it } from 'vitest';
import { normalizeError, sanitizeError } from '../normalize-error';

describe('normalizeError', () => {
  it('returns Error instances unchanged', () => {
    const error = new Error('Test error');
    const result = normalizeError(error);

    expect(result).toBe(error);
    expect(result.message).toBe('Test error');
  });

  it('converts string to Error', () => {
    const result = normalizeError('Something went wrong');

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('Something went wrong');
  });

  it('handles null', () => {
    const result = normalizeError(null);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('null');
  });

  it('handles undefined', () => {
    const result = normalizeError(undefined);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('undefined');
  });

  it('converts symbol to Error', () => {
    const sym = Symbol('test');
    const result = normalizeError(sym);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe(sym.toString());
  });

  it('converts function to Error', () => {
    const fn = function testFunction() {};
    const result = normalizeError(fn);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toContain('testFunction');
  });

  it('converts plain object to JSON string', () => {
    const obj = { code: 'ERR_001', details: 'Something failed' };
    const result = normalizeError(obj);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe(JSON.stringify(obj));
  });

  it('converts number to Error', () => {
    const result = normalizeError(404);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('404');
  });

  it('converts boolean to Error', () => {
    const result = normalizeError(false);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('false');
  });

  it('handles circular references', () => {
    const obj: Record<string, unknown> = { name: 'test' };
    obj.self = obj;

    const result = normalizeError(obj);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('[object Object]');
  });

  it('handles objects with custom toString', () => {
    const obj = {
      toString() {
        return 'Custom error representation';
      },
    };

    const result = normalizeError(obj);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('{}');
  });

  it('handles arrays', () => {
    const arr = [1, 2, 3];
    const result = normalizeError(arr);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe(JSON.stringify(arr));
  });

  it('preserves Error subclass types', () => {
    class CustomError extends Error {
      public constructor(message: string) {
        super(message);
        this.name = 'CustomError';
      }
    }

    const error = new CustomError('Custom message');
    const result = normalizeError(error);

    expect(result).toBe(error);
    expect(result.name).toBe('CustomError');
  });
});

describe('sanitizeError', () => {
  it('returns a serializable object from an Error', () => {
    const error = new Error('Test error');
    const result = sanitizeError(error);

    expect(result).toBeTypeOf('object');
    expect(result).toHaveProperty('message', 'Test error');
    expect(result).toHaveProperty('name', 'Error');
  });

  it('normalizes and serializes non-Error values', () => {
    const result = sanitizeError('plain string error');

    expect(result).toBeTypeOf('object');
    expect(result).toHaveProperty('message', 'plain string error');
  });

  it('handles null gracefully', () => {
    const result = sanitizeError(null);

    expect(result).toBeTypeOf('object');
    expect(result).toHaveProperty('message', 'null');
  });
});
