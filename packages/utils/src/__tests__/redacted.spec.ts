import { describe, expect, it } from 'vitest';
import { Redacted } from '../redacted';

describe('Redacted', () => {
  it('stores and retrieves the value', () => {
    const secret = 'my-secret-password';
    const redacted = new Redacted(secret);

    expect(redacted.value).toBe(secret);
  });

  it('returns [Redacted] when converted to string', () => {
    const redacted = new Redacted('sensitive-data');

    expect(redacted.toString()).toBe('[Redacted]');
    expect(String(redacted)).toBe('[Redacted]');
  });

  it('returns [Redacted] when serialized to JSON', () => {
    const redacted = new Redacted('api-key-123');

    expect(redacted.toJSON()).toBe('[Redacted]');
    expect(JSON.stringify(redacted)).toBe('"[Redacted]"');
  });

  it('works with objects', () => {
    const sensitiveObject = { username: 'admin', password: 'secret123' };
    const redacted = new Redacted(sensitiveObject);

    expect(redacted.value).toEqual(sensitiveObject);
    expect(redacted.toString()).toBe('[Redacted]');
  });

  it('works with arrays', () => {
    const sensitiveArray = ['key1', 'key2', 'key3'];
    const redacted = new Redacted(sensitiveArray);

    expect(redacted.value).toEqual(sensitiveArray);
    expect(JSON.stringify(redacted)).toBe('"[Redacted]"');
  });

  it('works with numbers', () => {
    const sensitiveNumber = 12345;
    const redacted = new Redacted(sensitiveNumber);

    expect(redacted.value).toBe(sensitiveNumber);
    expect(redacted.toString()).toBe('[Redacted]');
  });

  it('works with null', () => {
    const redacted = new Redacted(null);

    expect(redacted.value).toBeNull();
    expect(redacted.toString()).toBe('[Redacted]');
  });

  it('works with undefined', () => {
    const redacted = new Redacted(undefined);

    expect(redacted.value).toBeUndefined();
    expect(redacted.toString()).toBe('[Redacted]');
  });

  it('hides value in object spread', () => {
    const redacted = new Redacted('secret');
    const obj = { token: redacted, other: 'visible' };

    const serialized = JSON.stringify(obj);
    expect(serialized).toContain('[Redacted]');
    expect(serialized).not.toContain('secret');
  });

  it('prevents accidental logging of sensitive data', () => {
    const apiKey = 'sk-1234567890abcdef';
    const redacted = new Redacted(apiKey);

    const logMessage = `API Key: ${redacted}`;
    expect(logMessage).toBe('API Key: [Redacted]');
    expect(logMessage).not.toContain(apiKey);
  });

  it('works with nested objects in JSON', () => {
    const config = {
      apiKey: new Redacted('secret-key'),
      publicInfo: 'visible',
      auth: {
        token: new Redacted('bearer-token'),
        userId: 123,
      },
    };

    const json = JSON.stringify(config);
    expect(json).toContain('[Redacted]');
    expect(json).not.toContain('secret-key');
    expect(json).not.toContain('bearer-token');
    expect(json).toContain('visible');
    expect(json).toContain('123');
  });

  it('maintains type information', () => {
    const stringRedacted = new Redacted<string>('password');
    const numberRedacted = new Redacted<number>(42);
    const objectRedacted = new Redacted<{ key: string }>({ key: 'value' });

    expect(typeof stringRedacted.value).toBe('string');
    expect(typeof numberRedacted.value).toBe('number');
    expect(typeof objectRedacted.value).toBe('object');
  });
});
