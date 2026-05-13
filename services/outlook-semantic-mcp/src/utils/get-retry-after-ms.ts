import { GraphError } from '@microsoft/microsoft-graph-client';
import { isNonNullish } from 'remeda';
import { errors } from 'undici';
import { GenericRateLimitError } from './is-rate-limit-error';

// Extracts the Retry-After delay (ms) from Graph, undici, and GenericRateLimitError (including batched-cause arrays); returns the maximum found, or null.
export const getRetryAfterMs = (error: unknown): number | null => {
  if (error instanceof GraphError) {
    const retryAfter = error.headers?.get('Retry-After');
    if (retryAfter) {
      const seconds = parseInt(retryAfter, 10);
      if (!Number.isNaN(seconds)) {
        return seconds * 1000;
      }
    }
    return null;
  }
  if (error instanceof errors.ResponseError) {
    const headers = error.headers;
    if (headers && !Array.isArray(headers)) {
      const retryAfter = headers['retry-after'];
      if (typeof retryAfter === 'string') {
        const seconds = parseInt(retryAfter, 10);
        if (!Number.isNaN(seconds)) {
          return seconds * 1000;
        }
      }
    }
    return null;
  }
  if (error instanceof GenericRateLimitError) {
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
