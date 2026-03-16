import { GraphError } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { GlobalThrottleMiddleware } from './global-throttle.middleware';

const logger = new Logger('ThrottleRetry');
const MAX_RETRIES = 5;
const DEFAULT_BACKOFF_MS = 10_000;

function isThrottleError(error: unknown): error is GraphError {
  if (!(error instanceof GraphError)) return false;
  return (
    error.statusCode === 429 ||
    error.statusCode === 503 ||
    error.message.includes('too many requests')
  );
}

export async function withThrottleRetry<T>(
  fn: () => Promise<T>,
  label: string,
  userProfileId: string,
): Promise<T> {
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const waitMs = GlobalThrottleMiddleware.currentThrottleRemainingMs(userProfileId);
    if (waitMs > 0) {
      logger.log({ waitMs, label, attempt, userProfileId }, 'Waiting for per-user throttle before retry');
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }

    try {
      return await fn();
    } catch (error) {
      if (!isThrottleError(error) || attempt === MAX_RETRIES) {
        throw error;
      }

      const backoffMs = DEFAULT_BACKOFF_MS * 2 ** attempt;
      logger.warn(
        { label, attempt: attempt + 1, maxRetries: MAX_RETRIES, backoffMs, statusCode: error.statusCode, userProfileId },
        'Graph call throttled — scheduling retry',
      );

      GlobalThrottleMiddleware.activateThrottle(userProfileId, backoffMs);
      await new Promise((resolve) => setTimeout(resolve, backoffMs));
    }
  }

  throw new Error(`${label}: exhausted ${MAX_RETRIES} retries`);
}
