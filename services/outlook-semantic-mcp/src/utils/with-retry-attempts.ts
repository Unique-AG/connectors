import assert from 'node:assert';
import { getRetryAfterMs } from './get-retry-after-ms';
import { isRateLimitError } from './is-rate-limit-error';
import { sleep } from './sleep';

type PromiseFn<T> = () => Promise<T>;

/**
 * A convenience `onError` handler for `withRetryAttempts` that re-throws rate-limit errors on the
 * last attempt so callers surface 429s instead of silently swallowing them.
 * Pass it as `onError` when you want all other errors to be handled by `getResultFailure` but
 * still want the caller to observe rate-limit exhaustion.
 */
export const rethrowRateLimitError = (error: unknown, wasLastAttempt: boolean): void => {
  if (wasLastAttempt && isRateLimitError(error)) {
    throw error;
  }
};

/**
 * Runs `fn` up to `maxAttempts` times, retrying on every thrown error.
 *
 * Backoff between retries is exponential starting at `backOffMs`, unless the error carries a
 * `Retry-After` header (e.g. a 429 response) in which case that value is used instead.
 *
 * `onError` is called on every failure. If `onError` itself throws, the retry loop stops and the
 * exception propagates to the caller — use this to bail out early on unrecoverable errors or to
 * re-throw rate-limit errors on the last attempt (see `rethrowRateLimitError`).
 *
 * If all attempts are exhausted without `onError` throwing, `getResultFailure` is called with the
 * last error and its return value is used as the result — this lets callers express failure as a
 * typed value rather than an exception.
 */
export const withRetryAttempts = async <T, Err = T>({
  fn,
  maxAttempts = 3,
  backOffMs = 500,
  onError,
  getResultFailure,
}: {
  fn: PromiseFn<T>;
  maxAttempts?: number;
  backOffMs?: number;
  onError: (error: unknown, wasLastAttempt: boolean) => unknown | Promise<unknown>;
  getResultFailure: (error: unknown) => Err;
}): Promise<T | Err> => {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (error) {
      // If it's the last attempt and we are rate limited we throw the error again.
      await onError?.(error, attempt >= maxAttempts);

      if (attempt < maxAttempts) {
        await sleep(getRetryAfterMs(error) ?? backOffMs * 2 ** (attempt - 1));
      } else {
        return getResultFailure(error);
      }
    }
  }
  assert.fail(`Unreachable state`);
};
