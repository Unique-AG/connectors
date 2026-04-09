import { GraphError } from '@microsoft/microsoft-graph-client';
import Bottleneck from 'bottleneck';
import { errors } from 'undici';

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
  return false;
};
