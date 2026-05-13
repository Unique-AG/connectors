import { GraphError } from '@microsoft/microsoft-graph-client';
import { errors } from 'undici';
import { describe, expect, it } from 'vitest';
import { getRetryAfterMs } from './get-retry-after-ms';
import { GenericRateLimitError } from './is-rate-limit-error';

const makeGraphError = (retryAfterSeconds?: string): GraphError => {
  const error = new GraphError(429, 'Too Many Requests');
  if (retryAfterSeconds !== undefined) {
    error.headers = new Headers({ 'Retry-After': retryAfterSeconds });
  }
  return error;
};

// undici uses a custom Symbol.hasInstance, so we can satisfy instanceof without calling the constructor.
const kResponseError = Symbol.for('undici.error.UND_ERR_RESPONSE');
const makeResponseError = (retryAfterSeconds?: string): errors.ResponseError =>
  Object.assign(new Error('Too Many Requests'), {
    [kResponseError]: true,
    headers: retryAfterSeconds !== undefined ? { 'retry-after': retryAfterSeconds } : undefined,
    statusCode: 429,
  }) as unknown as errors.ResponseError;

describe('getRetryAfterMs', () => {
  describe('GraphError', () => {
    it('converts Retry-After seconds to milliseconds', () => {
      expect(getRetryAfterMs(makeGraphError('30'))).toBe(30_000);
    });

    it('returns null when no Retry-After header', () => {
      expect(getRetryAfterMs(makeGraphError())).toBeNull();
    });

    it('returns null when Retry-After is not a number', () => {
      expect(getRetryAfterMs(makeGraphError('Thu, 01 Jan 2026 00:00:00 GMT'))).toBeNull();
    });
  });

  describe('undici ResponseError', () => {
    it('converts retry-after seconds to milliseconds', () => {
      expect(getRetryAfterMs(makeResponseError('60'))).toBe(60_000);
    });

    it('returns null when no retry-after header', () => {
      expect(getRetryAfterMs(makeResponseError())).toBeNull();
    });

    it('returns null when headers is an array', () => {
      const error = Object.assign(new Error('Too Many Requests'), {
        [kResponseError]: true,
        headers: ['retry-after', '60'],
        statusCode: 429,
      }) as unknown as errors.ResponseError;
      expect(getRetryAfterMs(error)).toBeNull();
    });
  });

  describe('GenericRateLimitError', () => {
    it('delegates to single cause', () => {
      const inner = makeGraphError('45');
      const error = new GenericRateLimitError('rate limit', { cause: inner });
      expect(getRetryAfterMs(error)).toBe(45_000);
    });

    it('returns the maximum ms when cause is an array', () => {
      const error = new GenericRateLimitError('rate limit', {
        cause: [makeGraphError('30'), makeGraphError('60')],
      });
      expect(getRetryAfterMs(error)).toBe(60_000);
    });

    it('returns null when cause array has no retry-after values', () => {
      const error = new GenericRateLimitError('rate limit', {
        cause: [makeGraphError(), makeGraphError()],
      });
      expect(getRetryAfterMs(error)).toBeNull();
    });

    it('returns null when cause is undefined', () => {
      expect(getRetryAfterMs(new GenericRateLimitError('rate limit'))).toBeNull();
    });
  });

  describe('array of errors', () => {
    it('returns the maximum ms across all errors', () => {
      expect(getRetryAfterMs([makeGraphError('10'), makeGraphError('20')])).toBe(20_000);
    });

    it('returns null for an empty array', () => {
      expect(getRetryAfterMs([])).toBeNull();
    });

    it('returns null when no errors carry a retry-after value', () => {
      expect(getRetryAfterMs([makeGraphError(), makeGraphError()])).toBeNull();
    });
  });

  describe('unknown error types', () => {
    it('returns null for null', () => {
      expect(getRetryAfterMs(null)).toBeNull();
    });

    it('returns null for a plain Error', () => {
      expect(getRetryAfterMs(new Error('oops'))).toBeNull();
    });

    it('returns null for a string', () => {
      expect(getRetryAfterMs('some error')).toBeNull();
    });
  });
});
