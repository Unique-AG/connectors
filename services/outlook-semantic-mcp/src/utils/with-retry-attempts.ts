import assert from 'node:assert';
import { isObjectType } from 'remeda';
import { getRetryAfterMs } from './get-retry-after-ms';
import { isRateLimitError } from './is-rate-limit-error';
import { isTokenExpiredError } from './is-token-expired-error';
import { sleep } from './sleep';

type PromiseFn<T> = () => Promise<T>;

const RETRY_SYMBOL = Symbol(`Retry Without Backoff`);

interface RetryResponse {
  __type: typeof RETRY_SYMBOL;
  retryAfter: number | null | undefined;
}

/**
 * Return this from `onError` to signal the attempt should be retried.
 * Only valid when `wasLastAttempt` is false — on the last attempt you must throw or return a result.
 *
 * @param retryAfter - delay in ms before the next attempt; falls back to `backOffMs * 2^(attempt-1)`
 */
export const makeRetryResponse = (retryAfter?: number | null | undefined): RetryResponse => ({
  __type: RETRY_SYMBOL,
  retryAfter,
});

const isRetryResponse = (result: unknown): result is RetryResponse =>
  isObjectType(result) && '__type' in result && result.__type === RETRY_SYMBOL;

type OnErrorHanlderResponse<T> = T | Promise<T> | never | RetryResponse;

type OnErrorHanler<T> = (input: {
  error: unknown;
  attempt: number;
  wasLastAttempt: boolean;
}) => OnErrorHanlderResponse<T>;

/**
 * Standard `onError` handler for Microsoft Graph calls.
 * - On a rate-limit error (non-final attempt): retries after the `Retry-After` header delay.
 * - On a rate-limit error (final attempt): rethrows so the job moves to a failed/resumable state.
 * - On any other error: calls `createFailureResponseFactory` to produce a graceful result or to rethrow the error.
 *
 * @example
 * ```ts
 * await withRetryAttempts({
 *   fn: () => graphClient.get('/me/messages'),
 *   onError: makeDefaultOnErrorHandler((error) => {
 *     logger.error({ error }, 'Failed to fetch messages');
 *     return { status: 'failed' as const };
 *   }),
 * });
 * ```
 */
export function makeDefaultOnErrorHandler<T>(
  createFailureResponseFactory: (error: unknown) => T | never,
): OnErrorHanler<T> {
  // Default on error handler logic
  return ({ error, wasLastAttempt }) => {
    // 1. If it wasn't the last attempt and it's a rate limit error we return a retry response and we try to extract the delayed time for retry.
    if (!wasLastAttempt && isRateLimitError(error)) {
      return makeRetryResponse(getRetryAfterMs(error));
    }
    // 2. Rate limit errors on the last attempt are rethrown so the job moves to a failed/resumable state.
    //    Token expired errors are rethrown on any attempt — there is no point retrying with an expired token.
    //    If you need different behaviour, pass a custom onError instead of using this helper.
    if (isRateLimitError(error) || isTokenExpiredError(error)) {
      throw error;
    }
    // 3. If it's another kind of error we call the factory function to create the error response, it's the responsibility
    //    of the function to log the error / rethrow it or gracefully exit.
    return createFailureResponseFactory(error);
  };
}

/**
 * Runs `fn` up to `maxAttempts` times, delegating every thrown error to `onError`.
 *
 * `onError` must return one of:
 * - `makeRetryResponse(delayMs?)` — retry after an optional delay (only when `!wasLastAttempt`)
 * - a value of type `Err` — returned as the overall result
 * - `never` (i.e. throw) — propagates the error to the caller
 *
 * Use `makeDefaultOnErrorHandler` for the standard Microsoft Graph retry/rate-limit behaviour.
 * Build a custom `onError` only when you need different retry logic or a specific failure shape.
 *
 * @example
 * ```ts
 * const result = await withRetryAttempts({
 *   fn: () => graphClient.post('/me/sendMail', body),
 *   maxAttempts: 3,
 *   onError: makeDefaultOnErrorHandler((error) => {
 *     logger.error({ error }, 'sendMail failed');
 *     return { status: 'failed' as const };
 *   }),
 * });
 * ```
 */

export const withRetryAttempts = async <T, Err = T>({
  fn,
  maxAttempts = 3,
  backOffMs = 500,
  onError,
}: {
  fn: PromiseFn<T>;
  maxAttempts?: number;
  backOffMs?: number;
  onError: OnErrorHanler<Err>;
}): Promise<T | Err> => {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (error) {
      const result = await onError?.({ error, attempt, wasLastAttempt: attempt >= maxAttempts });

      if (isRetryResponse(result)) {
        assert(
          attempt < maxAttempts,
          `withRetryAttempts: Invalid response type from error handler, retry response can be returned if wasLastAttempt is false, on last attempt you need to throw or return a result`,
        );

        const retryAfter =
          result.retryAfter ?? getRetryAfterMs(error) ?? backOffMs * 2 ** (attempt - 1);
        await sleep(retryAfter);
        continue;
      }

      return result;
    }
  }
  assert.fail(`withRetryAttempts: Unreachable state`);
};
