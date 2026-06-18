import { describe, expect, it } from 'vitest';
import { Redacted } from '../redacted';

describe('Redacted', () => {
  describe('value', () => {
    it('exposes the original value via the .value getter', () => {
      const r = new Redacted('secret-token');

      expect(r.value).toBe('secret-token');
    });

    it('works with non-string values', () => {
      const r = new Redacted(42);

      expect(r.value).toBe(42);
    });
  });

  describe('toString', () => {
    it('returns "[Redacted]" instead of the actual value', () => {
      const r = new Redacted('super-secret');

      expect(r.toString()).toBe('[Redacted]');
      expect(String(r)).toBe('[Redacted]');
    });
  });

  describe('toJSON', () => {
    it('serializes to "[Redacted]" in JSON output', () => {
      const r = new Redacted('my-password');

      expect(JSON.stringify({ token: r })).toBe('{"token":"[Redacted]"}');
    });

    it('does not leak the secret when used in template literals', () => {
      const r = new Redacted('leaked-secret');

      expect(`${r}`).toBe('[Redacted]');
    });
  });
});
