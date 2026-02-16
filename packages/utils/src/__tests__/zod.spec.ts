import { typeid as libtypeid, TypeID } from 'typeid-js';
import { describe, expect, it } from 'vitest';
import z from 'zod/v4';
import { Redacted } from '../redacted';
import { isoDatetimeToDate, json, redacted, stringToURL, typeid } from '../zod';

describe('json', () => {
  const schema = json(z.object({ name: z.string(), age: z.number() }));

  describe('decode', () => {
    it('parses valid JSON string into object matching schema', () => {
      const result = z.parse(schema, '{"name":"Alice","age":30}');

      expect(result).toEqual({ name: 'Alice', age: 30 });
    });

    it('rejects invalid JSON string', () => {
      const result = z.safeParse(schema, '{not valid json}');

      expect(result.success).toBe(false);
    });

    it('rejects JSON that does not match schema', () => {
      const result = z.safeParse(schema, '{"name":123}');

      expect(result.success).toBe(false);
    });
  });

  describe('encode', () => {
    it('serializes object to JSON string', () => {
      const encoded = z.encode(schema, { name: 'Alice', age: 30 });

      expect(encoded).toBe('{"name":"Alice","age":30}');
    });

    it('rejects circular references during encode', () => {
      const schema = json(z.record(z.string(), z.unknown()));
      const circular: Record<string, unknown> = { name: 'test' };
      circular.self = circular;

      expect(() => z.encode(schema, circular)).toThrow();
    });
  });
});

describe('typeid', () => {
  const prefixedSchema = typeid('user');
  const unprefixedSchema = typeid();

  describe('decode', () => {
    it('parses valid typeid string into TypeID instance', () => {
      const tid = libtypeid('user');
      const input = tid.toString();

      const result = z.parse(prefixedSchema, input);

      expect(result).toBeInstanceOf(TypeID);
      expect(result.toString()).toBe(input);
    });

    it('validates prefix when provided', () => {
      const tid = libtypeid('order');
      const input = tid.toString();

      const result = z.safeParse(prefixedSchema, input);

      expect(result.success).toBe(false);
    });

    it('accepts any prefix when none specified', () => {
      const tid = libtypeid('order');
      const input = tid.toString();

      const result = z.parse(unprefixedSchema, input);

      expect(result).toBeInstanceOf(TypeID);
    });

    it('rejects invalid typeid string', () => {
      const result = z.safeParse(prefixedSchema, 'not-a-typeid');

      expect(result.success).toBe(false);
    });
  });

  describe('encode', () => {
    it('serializes TypeID to string', () => {
      const tid = libtypeid('user');

      const encoded = z.encode(prefixedSchema, tid);

      expect(encoded).toBe(tid.toString());
      expect(typeof encoded).toBe('string');
    });
  });
});

describe('stringToURL', () => {
  const schema = stringToURL();

  describe('decode', () => {
    it('converts valid URL string to URL instance', () => {
      const result = z.parse(schema, 'https://example.com/path?q=1');

      expect(result).toBeInstanceOf(URL);
      expect(result.hostname).toBe('example.com');
      expect(result.pathname).toBe('/path');
      expect(result.searchParams.get('q')).toBe('1');
    });
  });

  describe('decode error', () => {
    it('rejects invalid URL string', () => {
      const result = z.safeParse(schema, 'not a url');

      expect(result.success).toBe(false);
    });
  });

  describe('encode', () => {
    it('converts URL to href string', () => {
      const url = new URL('https://example.com/path');

      const encoded = z.encode(schema, url);

      expect(encoded).toBe('https://example.com/path');
      expect(typeof encoded).toBe('string');
    });
  });
});

describe('isoDatetimeToDate', () => {
  const schema = isoDatetimeToDate();

  describe('decode', () => {
    it('converts ISO datetime string to Date instance', () => {
      const isoString = '2025-06-15T10:30:00.000Z';

      const result = z.parse(schema, isoString);

      expect(result).toBeInstanceOf(Date);
      expect(result.toISOString()).toBe(isoString);
    });
  });

  describe('decode error', () => {
    it('rejects non-ISO string', () => {
      const result = z.safeParse(schema, 'not-a-date');

      expect(result.success).toBe(false);
    });

    it('rejects plain date without time component', () => {
      const result = z.safeParse(schema, '2025-06-15');

      expect(result.success).toBe(false);
    });
  });

  describe('encode', () => {
    it('converts Date to ISO string', () => {
      const date = new Date('2025-06-15T10:30:00.000Z');

      const encoded = z.encode(schema, date);

      expect(encoded).toBe('2025-06-15T10:30:00.000Z');
      expect(typeof encoded).toBe('string');
    });
  });
});

describe('redacted', () => {
  const schema = redacted(z.string());

  describe('decode', () => {
    it('wraps value in Redacted instance', () => {
      const result = z.parse(schema, 'secret-token');

      expect(result).toBeInstanceOf(Redacted);
      expect(result.value).toBe('secret-token');
    });

    it('wraps object value in Redacted instance', () => {
      const objectSchema = redacted(z.object({ key: z.string() }));

      const result = z.parse(objectSchema, { key: 'value' });

      expect(result).toBeInstanceOf(Redacted);
      expect(result.value).toEqual({ key: 'value' });
    });

    it('rejects value that does not match inner schema', () => {
      const result = z.safeParse(schema, 123);

      expect(result.success).toBe(false);
    });
  });

  describe('encode', () => {
    it('extracts raw value from Redacted', () => {
      const wrapped = new Redacted('secret-token');

      const encoded = z.encode(schema, wrapped);

      expect(encoded).toBe('secret-token');
    });

    it('extracts object value from Redacted', () => {
      const objectSchema = redacted(z.object({ key: z.string() }));
      const wrapped = new Redacted({ key: 'value' });

      const encoded = z.encode(objectSchema, wrapped);

      expect(encoded).toEqual({ key: 'value' });
    });
  });
});
