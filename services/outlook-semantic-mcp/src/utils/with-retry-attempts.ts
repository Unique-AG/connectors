import assert from 'node:assert';
import { isRateLimitError } from './is-rate-limit-error';
import { sleep } from './sleep';

type PromiseFn<T> = () => Promise<T>;

export const rethrowRateLimitError = (error: unknown, wasLastAttempt: boolean): void => {
  if (wasLastAttempt && isRateLimitError(error)) {
    throw error;
  }
};

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
        await sleep(backOffMs * 2 ** (attempt - 1));
      } else {
        return getResultFailure(error);
      }
    }
  }
  assert.fail(`Unreachable state`);
};
