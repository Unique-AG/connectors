import { GraphError } from '@microsoft/microsoft-graph-client';
import Bottleneck from 'bottleneck';
import { errors } from 'undici';

export class GenericRateLimitError extends Error {
  public constructor(message?: string, options?: ErrorOptions) {
    super(message, options);
    this.name = `GenericRateLimitError`;
  }
}

export const isRateLimitError = (error: unknown): boolean => {
  const isMicrosoftRateLimit = error instanceof GraphError && error.statusCode === 429;
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
