import { GraphError } from '@microsoft/microsoft-graph-client';
import { isNonNullish, isNumber } from 'remeda';
import { errors } from 'undici';
import { GenericRateLimitError } from './is-rate-limit-error';
import { parseRetryAfterMs } from './parse-retry-after-ms';

// Extracts the Retry-After delay (ms) from Graph, undici, and GenericRateLimitError (including batched-cause arrays); returns the maximum found, or null.
export const getRetryAfterMs = (error: unknown): number | null => {
  if (error instanceof GraphError) {
    return parseRetryAfterMs(error.headers?.get('Retry-After'));
  }
  if (error instanceof errors.ResponseError) {
    const headers = error.headers;
    if (headers && !Array.isArray(headers)) {
      const retryAfter = headers['retry-after'];
      if (typeof retryAfter === 'string') {
        return parseRetryAfterMs(retryAfter);
      }
    }
    return null;
  }
  if (error instanceof GenericRateLimitError) {
    if (isNumber(error.retryAfter)) {
      return error.retryAfter;
    }
    if (Array.isArray(error.cause)) {
      const nonNullMs = error.cause.map(getRetryAfterMs).filter(isNonNullish);
      if (!nonNullMs.length) {
        return null;
      }

      return Math.max(...nonNullMs);
    }
    return getRetryAfterMs(error.cause);
  }
  if (Array.isArray(error)) {
    const values = error.map(getRetryAfterMs).filter((v): v is number => v !== null);
    return values.length > 0 ? Math.max(...values) : null;
  }
  return null;
};
