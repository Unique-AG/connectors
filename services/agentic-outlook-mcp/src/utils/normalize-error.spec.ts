import { describe, expect, it } from 'vitest';
import { normalizeError } from './normalize-error';

describe('normalize-error', () => {
  it('returns the error as-is if it is already an Error instance', () => {
    const originalError = new Error('Test error');
    const result = normalizeError(originalError);

    expect(result).toBe(originalError);
    expect(result.message).toBe('Test error');
  });

  it('converts string to Error instance', () => {
    const result = normalizeError('String error message');

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('String error message');
  });

  it('converts number to Error instance', () => {
    const result = normalizeError(404);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('404');
  });

  it('converts null to Error instance', () => {
    const result = normalizeError(null);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('null');
  });

  it('converts undefined to Error instance', () => {
    const result = normalizeError(undefined);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('undefined');
  });

  it('converts object to Error instance with JSON representation', () => {
    const errorObject = { code: 'ECONNREFUSED', port: 3000 };
    const result = normalizeError(errorObject);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('{"code":"ECONNREFUSED","port":3000}');
  });

  it('converts array to Error instance with JSON representation', () => {
    const errorArray = ['error1', 'error2'];
    const result = normalizeError(errorArray);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('["error1","error2"]');
  });

  it('handles circular references in objects', () => {
    // biome-ignore lint/suspicious/noExplicitAny: Testing circular reference handling
    const circularObject: any = { name: 'test' };
    circularObject.self = circularObject;

    const result = normalizeError(circularObject);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toContain('[object Object]');
  });

  it('handles boolean values', () => {
    const result = normalizeError(true);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('true');
  });

  it('handles symbol values', () => {
    const sym = Symbol('test');
    const result = normalizeError(sym);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toBe('Symbol(test)');
  });

  it('handles function values', () => {
    const func = function testFunction() {};
    const result = normalizeError(func);

    expect(result).toBeInstanceOf(Error);
    expect(result.message).toContain('function testFunction');
  });
});
