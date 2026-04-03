import { describe, expect, it } from 'vitest';
import { UniquePublicSdkOptionsSchema } from '../unique-public-sdk.options';

const context = describe;

describe('UniquePublicSdkOptionsSchema', () => {
  const minimalValid = {
    apiBaseUrl: 'https://api.unique.app',
    serviceHeaders: { authorization: 'Bearer test' },
  };

  context('with minimal valid input', () => {
    it('applies default apiVersion', () => {
      const result = UniquePublicSdkOptionsSchema.parse(minimalValid);
      expect(result.apiVersion).toBe('2023-12-06');
    });

    it('applies default retry settings', () => {
      const result = UniquePublicSdkOptionsSchema.parse(minimalValid);
      expect(result.retry).toEqual({
        maxAttempts: 3,
        baseDelayMs: 200,
        maxDelayMs: 10_000,
      });
    });
  });

  context('with invalid apiBaseUrl', () => {
    it('rejects non-URL strings', () => {
      expect(() =>
        UniquePublicSdkOptionsSchema.parse({
          ...minimalValid,
          apiBaseUrl: 'not-a-url',
        }),
      ).toThrow();
    });
  });

  context('with empty serviceHeaders', () => {
    it('accepts empty headers', () => {
      const result = UniquePublicSdkOptionsSchema.parse({
        ...minimalValid,
        serviceHeaders: {},
      });
      expect(result.serviceHeaders).toEqual({});
    });
  });

  context('with storageInternalBaseUrl', () => {
    it('accepts a valid URL', () => {
      const result = UniquePublicSdkOptionsSchema.parse({
        ...minimalValid,
        storageInternalBaseUrl: 'http://storage.internal:10000',
      });
      expect(result.storageInternalBaseUrl).toBe('http://storage.internal:10000');
    });

    it('rejects invalid URLs', () => {
      expect(() =>
        UniquePublicSdkOptionsSchema.parse({
          ...minimalValid,
          storageInternalBaseUrl: 'not-a-url',
        }),
      ).toThrow();
    });
  });

  context('with custom retry settings', () => {
    it('accepts valid overrides', () => {
      const result = UniquePublicSdkOptionsSchema.parse({
        ...minimalValid,
        retry: { maxAttempts: 5, baseDelayMs: 100, maxDelayMs: 5000 },
      });
      expect(result.retry).toEqual({
        maxAttempts: 5,
        baseDelayMs: 100,
        maxDelayMs: 5000,
      });
    });

    it('rejects negative maxAttempts', () => {
      expect(() =>
        UniquePublicSdkOptionsSchema.parse({
          ...minimalValid,
          retry: { maxAttempts: -1 },
        }),
      ).toThrow();
    });

    it('rejects zero baseDelayMs', () => {
      expect(() =>
        UniquePublicSdkOptionsSchema.parse({
          ...minimalValid,
          retry: { baseDelayMs: 0 },
        }),
      ).toThrow();
    });
  });
});
