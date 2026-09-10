import { UpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it } from 'vitest';
import { isTokenExpiredError } from '../is-token-expired-error';

function graphError(statusCode: number): GraphError {
  const error = new GraphError(statusCode, 'Error while processing response.');
  error.statusCode = statusCode;
  return error;
}

describe(isTokenExpiredError.name, () => {
  it('is true for a Graph 401', () => {
    expect(isTokenExpiredError(graphError(401))).toBe(true);
  });

  it('is true for a revoked grant, which callers must classify the same way', () => {
    expect(isTokenExpiredError(new UpstreamCredentialRevokedError('invalid_grant'))).toBe(true);
  });

  it('is false for other Graph failures and unrelated errors', () => {
    expect(isTokenExpiredError(graphError(403))).toBe(false);
    expect(isTokenExpiredError(graphError(429))).toBe(false);
    expect(isTokenExpiredError(new Error('network error'))).toBe(false);
  });
});
