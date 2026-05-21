import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Injectable } from '@nestjs/common';
import { isTokenExpiredError } from '~/utils/is-token-expired-error';
import { CannotReadErrorReason, DataAccessError } from '../utils/data-access-error';
import { isDelegatedAccessNotAvailableError } from '../utils/is-delegated-access-not-available-error';

export type TestReadAccessFromGraphEndpointOutput =
  | { canRead: true }
  | { canRead: false }
  | DataAccessError;

@Injectable()
export class TestReadAccessFromGraphEndpointQuery {
  public async run({
    client,
    endpoint,
  }: {
    client: Client;
    endpoint: string;
  }): Promise<TestReadAccessFromGraphEndpointOutput> {
    try {
      await client.api(endpoint).select('id').top(1).get();
      return { canRead: true };
    } catch (error) {
      if (isDelegatedAccessNotAvailableError(error)) {
        return { canRead: false };
      }
      if (error instanceof GraphError) {
        if (isTokenExpiredError(error)) {
          return { canRead: false, reason: CannotReadErrorReason.TokenExpired, error };
        }
        if (error.statusCode === 429 || (error.statusCode >= 500 && error.statusCode < 600)) {
          return { canRead: false, reason: CannotReadErrorReason.TransientError, error };
        }
      }
      return { canRead: false, reason: CannotReadErrorReason.UnexpectedError, error };
    }
  }
}
