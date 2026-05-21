import { GraphError } from '@microsoft/microsoft-graph-client';
import Bottleneck from 'bottleneck';
import { errors } from 'undici';

// This rate limit error is internal to the app. It should be used in cases where we want to retry with exponential backoff
// a batch of requests.
// A clear example is Promise.allSettled(requstsToMsGraph)
// Then we check the results and if any of them returned 429 and we want to retry we can throw
// a GenericRateLimitError, to signal that we can retry the whole batch.
export class GenericRateLimitError extends Error {
  public readonly retryAfter: number | undefined | null;

  public constructor(message?: string, retryAfter?: number | null, options?: ErrorOptions) {
    super(message, options);
    this.retryAfter = retryAfter;
    this.name = `GenericRateLimitError`;
  }
}

export const isRateLimitError = (error: unknown): boolean => {
  const isMicrosoftRateLimit =
    error instanceof GraphError && (error.statusCode === 429 || error.statusCode === 503);
  if (isMicrosoftRateLimit) {
    return true;
  }
  const isUniqueRateLimit = error instanceof errors.ResponseError && error.statusCode === 429;
  if (isUniqueRateLimit) {
    return true;
  }
  const isBottleneckRateLimit = error instanceof Bottleneck.BottleneckError;
  if (isBottleneckRateLimit) {
    return true;
  }
  const isGenericRateLimitError = error instanceof GenericRateLimitError;
  if (isGenericRateLimitError) {
    return true;
  }
  return false;
};
